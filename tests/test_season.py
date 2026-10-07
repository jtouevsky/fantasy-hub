import pytest

import demo_data
from models import PlayerInfo
from season import IR_DEFAULT_GAMES, Season
from strategy import Strategy
from valuation import ValueModel


def build(week=5):
    snap = demo_data.build_demo_snapshot(week=week)
    fas = demo_data.build_demo_free_agents(week=week)
    for t in snap.teams:
        for p in t.roster:
            p.bye_week = 0                           # keep the demo deterministic unless a test sets a bye
    return snap, fas, Season(snap, ValueModel(snap, fas), Strategy(), fas)


def mk(pid, pos="WR", ppg=14.0, status="ACTIVE", slot="BE", bye=0, ret=-1.0):
    return PlayerInfo(pid, f"P{pid}", pos, "XXX", status, slot, [pos, "BE"], week_proj=ppg, total_points=ppg * 4, games_played=4, season_proj_ppg=ppg, bye_week=bye, return_games=ret)


def test_weeks_and_playoff_weighting_come_from_league_settings():
    snap, fas, s = build()
    assert s.weeks == list(range(5, snap.final_week + 1))
    assert s.weights[snap.reg_season_weeks] == 1.0 and s.weights[snap.reg_season_weeks + 1] == 1.5 == s.weights[snap.final_week]


def test_ir_player_is_valued_by_a_return_timeline_not_a_flat_discount():
    snap, fas, s = build()
    ir = mk(1, status="INJURY_RESERVE")
    curve = [s.avail(ir, w) for w in s.weeks]
    assert curve[0] < 0.05 and curve == sorted(curve)                        # out now, monotonically more likely to be back
    assert curve[-1] > 0.8 and curve[-1] <= 0.92 + 1e-9                      # likely back for the playoffs, with a re-injury discount
    assert s.timeline(ir).source == "default" and s.timeline(ir).expected_games_out == IR_DEFAULT_GAMES
    short = mk(2, status="INJURY_RESERVE", ret=2.0)
    long_ = mk(3, status="INJURY_RESERVE", ret=9.0)
    assert s.raw_ros(short) > s.raw_ros(ir) > s.raw_ros(long_) > 0            # news timeline moves value; even a long absence is not zero
    assert s.timeline(short).source == "news" and "from news" in s.timeline(short).note


def test_flat_old_model_would_have_given_the_two_ir_players_the_same_value():
    snap, fas, s = build()
    a, b = mk(4, status="INJURY_RESERVE", ret=2.0), mk(5, status="INJURY_RESERVE", ret=10.0)
    assert s.par(a) != pytest.approx(s.par(b), abs=1.0)                       # timeline-sensitive


def test_bye_week_zeroes_that_week_only_and_questionable_applies_to_this_week_only():
    snap, fas, s = build()
    p = mk(6, bye=7)
    assert s.avail(p, 7) == 0.0 and s.avail(p, 6) == 1.0 and s.avail(p, 8) == 1.0
    q = mk(7, status="QUESTIONABLE")
    assert s.avail(q, 5) == pytest.approx(0.59) and s.avail(q, 6) == 1.0
    assert s.raw_ros(p) < s.raw_ros(mk(8))                                     # the bye costs points


def test_value_is_signed_and_ranking_has_no_ties_at_zero():
    snap, fas, s = build()
    below = mk(9, "WR", ppg=4.0)
    assert s.par(below) < 0                                                    # below replacement is NEGATIVE, not clipped to 0
    bench = [mk(10 + i, "WR", ppg=2.0 + 0.7 * i) for i in range(6)]
    keys = [s.rank_key(p) for p in bench]
    assert len(set(round(k, 3) for k in keys)) == 6 and keys == sorted(keys)  # distinct, ordered by raw value + upside


def test_upside_breaks_ties_between_equal_raw_players():
    snap, fas, s = build()
    a, b = mk(20, ppg=8.0), mk(21, ppg=8.0)
    b.tags = [["buy low", "x"]]
    b.season_proj_ppg = 11.0
    assert s.rank_key(b) > s.rank_key(a)


def test_season_lineup_is_week_by_week_and_holes_use_the_best_real_free_agent():
    snap, fas, s = build()
    me = snap.my_team.roster
    full = s.season_lineup(me)
    assert len(full["weeks"]) == len(s.weeks) and full["total"] == pytest.approx(sum(s.weights[w] * v for w, v in full["weeks"]))
    qbs = [p for p in me if p.position == "QB"]
    hole = s.season_lineup([p for p in me if p.position != "QB"])
    best_fa_qb = max((p for p in s.fa_pool if p.position == "QB"), key=lambda p: s.raw_ros_noncached(p))
    assert hole["starts"].get(best_fa_qb.player_id, 0) == len(s.weeks)        # the hole is filled by the best REAL free-agent QB, every week
    assert hole["total"] < full["total"]


def test_bye_week_hole_shows_up_in_that_week_only():
    snap, fas, s = build()
    me = [dict_p for dict_p in snap.my_team.roster]
    te = next(p for p in me if p.position == "TE" and p.lineup_slot == "TE")
    te.bye_week = 8
    weeks = dict(s.season_lineup([p for p in me if not (p.position == "TE" and p is not te)], use_pool=False)["weeks"])
    assert weeks[8] < weeks[7] and weeks[8] < weeks[9] or weeks[8] <= min(weeks[7], weeks[9]) + 1e-9


def test_ir_slot_players_do_not_use_a_bench_spot_and_worst_droppable_skips_ir():
    snap, fas, s = build()
    roster = snap.my_team.roster
    n = s.roster_count(roster)
    ir = mk(30, status="INJURY_RESERVE", slot="IR")
    assert s.roster_count(roster + [ir]) == n                                  # IR slot: free
    bad = mk(31, ppg=1.0)
    assert s.worst_droppable(roster + [ir, bad]).player_id == 31 and s.worst_droppable(roster + [ir]).lineup_slot != "IR"
    assert s.worst_droppable(roster + [bad], protect={31}).player_id != 31
