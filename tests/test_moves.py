import demo_data
import moves as mv
from models import PlayerInfo
from season import Season
from strategy import Strategy
from valuation import ValueModel

NOW = 1_800_000_000.0


def mk(pid, pos, ppg, slot="BE", team="XXX", **kw):
    return PlayerInfo(pid, f"P{pid}", pos, team, kw.pop("status", "ACTIVE"), slot, [pos, "BE"], week_proj=kw.pop("proj", ppg), total_points=ppg * 4, games_played=kw.pop("gp", 4),
                      season_proj_ppg=ppg, bye_week=0, **kw)


def build(activity=(), strategy=None, fas_extra=(), mine_extra=(), dst=None):
    snap = demo_data.build_demo_snapshot()
    fas = list(demo_data.build_demo_free_agents()) + list(fas_extra)
    for t in snap.teams:
        for p in t.roster:
            p.bye_week = 0
    for p in fas:
        p.bye_week = 0
    snap.my_team.roster += list(mine_extra)
    st = strategy or Strategy()
    s = Season(snap, ValueModel(snap, fas), st, fas)
    return snap, fas, mv.MoveEngine(snap, s, st, fas, activity, dst=dst, now=NOW)


def test_streaming_dst_keeps_current_unless_gain_clears_threshold_and_just_added_is_not_churned():
    snap, fas, _ = build()
    cur = next(p for p in snap.my_team.roster if p.position == "D/ST")
    best_alt = lambda gain, pid: mk(pid, "D/ST", 6.0, proj=cur.week_proj + gain, team="PNE")
    snap, fas, eng = build(fas_extra=[best_alt(1.0, 7001)])
    sp = eng.stream_pick("D/ST")
    assert not sp.swap and "Keep your current" in sp.reason                       # +1.0 < +2.0 threshold
    snap, fas, eng = build(fas_extra=[best_alt(3.5, 7002)])
    cur = next(p for p in snap.my_team.roster if p.position == "D/ST")
    assert eng.stream_pick("D/ST").swap
    # the D/ST I already hold can never be proposed as an add (it's on my roster) and the cap blocks a 2nd D/ST without a swap
    m = eng.evaluate_move(fas[-1], next(p for p in snap.my_team.roster if p.position == "RB" and p.lineup_slot == "BE"))
    assert not m.ok and any("D/ST" in b for b in m.blocked)


def test_dst_ping_pong_is_blocked_after_a_recent_drop():
    acts = [{"team_id": 1, "player_id": 7003, "action": "DROPPED", "ts": NOW - 2 * 86400}]
    alt = mk(7003, "D/ST", 6.0, proj=14.0, team="PNE")
    snap, fas, eng = build(acts, fas_extra=[alt])
    assert eng.recently_dropped(alt) is not None
    sp = eng.stream_pick("D/ST")
    assert sp.best is None or sp.best.player_id != 7003


def test_with_two_qbs_a_third_is_never_proposed_and_cannot_cost_an_rb():
    snap, fas, eng = build()
    assert eng.count(snap.my_team.roster, "QB") >= 2
    qb = mk(7010, "QB", 7.2, proj=17.9, team="NYJ", gp=4)                                  # the Kyler Murray case: one ESPN outlier
    rb = next(p for p in snap.my_team.roster if p.position == "RB" and p.lineup_slot == "BE")
    m = eng.evaluate_move(qb, rb)
    assert not m.ok and any("cap" in b.lower() or "QB" in b for b in m.blocked)
    assert all(x.add.position != "QB" for x in eng.find_moves().moves)
    # a QB swap inside the position is allowed only if the numbers justify it
    other_qb = next(p for p in snap.my_team.roster if p.position == "QB" and p.lineup_slot == "BE")
    assert not any("cap" in b.lower() for b in eng.evaluate_move(qb, other_qb).blocked)


def test_one_week_spike_is_speculative_and_needs_a_bigger_gain():
    snap, fas, _ = build()
    wr = mk(7020, "WR", 6.0, proj=16.0, team="NYJ")                                      # 6 ppg player projected 16 this week
    snap, fas, eng = build(fas_extra=[wr])
    bench = min((p for p in snap.my_team.roster if p.position == "WR" and p.lineup_slot == "BE"), key=lambda p: p.total_points)
    m = eng.evaluate_move(wr, bench)
    assert "speculative" in m.flags and m.confidence == "low"
    assert eng.strategy.speculative_extra_gain > 0


def test_never_drop_a_starter_caliber_player_for_a_backup():
    snap, fas, eng = build()
    starter_rb = next(p for p in snap.my_team.roster if p.position == "RB" and p.lineup_slot == "RB")
    backup = mk(7030, "TE", 3.0, team="NYJ")
    m = eng.evaluate_move(backup, starter_rb)
    assert not m.ok


def test_recently_added_player_is_protected():
    snap, fas, _ = build()
    bench = min((p for p in snap.my_team.roster if p.lineup_slot == "BE" and p.position == "WR"), key=lambda p: p.total_points)
    acts = [{"team_id": 1, "player_id": bench.player_id, "action": "FA ADDED", "ts": NOW - 2 * 86400}]
    star = mk(7040, "WR", 19.0, team="NYJ")
    snap, fas, eng = build(acts, fas_extra=[star])
    bench = next(p for p in snap.my_team.roster if p.player_id == bench.player_id)
    m = eng.evaluate_move(star, bench)
    assert any("ago" in b for b in m.blocked)
    assert all(not (x.drop and x.drop.player_id == bench.player_id) for x in eng.find_moves().moves)


def test_no_good_moves_returns_a_no_move_answer():
    snap, fas, eng = build(fas_extra=[])
    for p in fas:
        p.week_proj = p.season_proj_ppg = 1.0
        p.total_points = 4.0
    snap, fas, eng2 = build()
    for p in eng2.fas:
        p.week_proj = p.season_proj_ppg = 1.0
        p.total_points = 4.0
    ms = eng2.find_moves()
    assert ms.empty and "lineup is set" in ms.no_move_reason or not ms.moves
    d = ms.to_dict()
    assert "no_move_needed" in d


def test_a_real_upgrade_is_found_with_a_short_reason_and_valid_drop():
    star = mk(7050, "RB", 21.0, team="NYJ")
    snap, fas, eng = build(fas_extra=[star])
    ms = eng.find_moves()
    top = [m for m in ms.moves if m.add.player_id == 7050]
    assert top and top[0].ok and top[0].gain_ros > 5 and top[0].drop is not None
    assert "0.0" not in top[0].reason and len(top[0].reason) < 330
    assert top[0].drop.lineup_slot != "IR"
