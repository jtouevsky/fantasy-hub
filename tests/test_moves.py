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


def stab(ppg, touches, snap, td_share=0.15, dep=False, vol=False, raw=None):
    return {"ppg": ppg, "g": 8, "raw_ppg": raw if raw is not None else ppg, "touches_pg": touches, "snap_pct": snap, "td_share": td_share, "td_act_pg": 0.9, "td_exp_pg": 0.4,
            "targets_pg": touches, "carries_pg": 0.0, "dependent": dep, "volume_backed": vol, "r": [0.4, 0.9, 1.5], "rz_touch_pg": 1.0}


def test_td_fluke_with_low_opportunity_is_not_recommended_even_off_a_big_week():
    fluke = mk(7100, "WR", 9.0, proj=17.0, team="NYJ", gp=8)
    fluke.stable = stab(7.0, 3.5, 0.35, td_share=0.55, dep=True, raw=14.0)
    snap, fas, eng = build(fas_extra=[fluke])
    bench = min((p for p in snap.my_team.roster if p.position == "WR" and p.lineup_slot == "BE"), key=lambda p: p.total_points)
    m = eng.evaluate_move(fluke, bench)
    assert not m.ok and any("opportunity" in b.lower() or "td-dependent" in b.lower() or "doesn't beat" in b for b in m.blocked)
    assert all(x.add.player_id != 7100 for x in eng.find_moves().moves)


def test_high_volume_receiver_with_no_tds_passes_the_gate_and_shows_evidence():
    vol = mk(7101, "WR", 15.5, team="NYJ", gp=8)
    vol.stable = stab(15.5, 11.0, 0.88, td_share=0.0, vol=True, raw=12.0)
    snap, fas, eng = build(fas_extra=[vol])
    ms = eng.find_moves()
    top = [m for m in ms.moves if m.add.player_id == 7101]
    assert top and top[0].ok and top[0].evidence["opportunity"]["touches_pg"] == 11.0
    rules = " ".join(top[0].evidence["rules"])
    assert "Real opportunity" in rules and "Stability-weighted value" in rules
    assert top[0].evidence["distribution"]["floor"] < top[0].evidence["distribution"]["ceiling"]
    assert top[0].confidence in ("medium", "high")


def test_fluke_loses_to_volume_when_both_are_available():
    fluke = mk(7102, "WR", 9.0, proj=17.0, team="NYJ", gp=8)
    fluke.stable = stab(7.0, 3.5, 0.35, td_share=0.55, dep=True, raw=14.0)
    vol = mk(7103, "WR", 12.0, team="NYJ", gp=8)
    vol.stable = stab(15.0, 10.0, 0.85, vol=True, raw=12.0)
    snap, fas, eng = build(fas_extra=[fluke, vol])
    adds = [m.add.player_id for m in eng.find_moves().moves]
    assert 7103 in adds and 7102 not in adds


def test_low_opportunity_is_allowed_only_with_a_specific_sourced_reason():
    backup = mk(7104, "RB", 8.0, team="NYJ", gp=8)
    backup.stable = stab(13.0, 3.0, 0.30)                      # value is fine, opportunity is not (yet)
    snap, fas, eng = build(fas_extra=[backup])
    drop = min((p for p in snap.my_team.roster if p.position == "RB" and p.lineup_slot == "BE"), key=lambda p: p.total_points)
    assert not eng.evaluate_move(backup, drop).ok
    snap, fas, eng2 = build(fas_extra=[backup])
    eng2.news_reasons = {7104: "injury cascade: RB1 is out for the season and he is next up (+6 pts)"}
    drop = min((p for p in snap.my_team.roster if p.position == "RB" and p.lineup_slot == "BE"), key=lambda p: p.total_points)
    m = eng2.evaluate_move(backup, drop)
    assert not any("opportunity" in b.lower() for b in m.blocked)
    assert "specific reason" in " ".join(m.evidence["rules"]).lower()


def test_add_must_beat_the_player_it_replaces_not_replacement_level():
    meh = mk(7105, "WR", 6.0, team="NYJ", gp=8)
    meh.stable = stab(6.0, 8.0, 0.8)
    snap, fas, eng = build(fas_extra=[meh])
    best_bench = max((p for p in snap.my_team.roster if p.position == "WR" and p.lineup_slot == "BE"), key=lambda p: p.total_points)
    m = eng.evaluate_move(meh, best_bench)
    assert not m.ok and any("doesn't beat" in b for b in m.blocked)
