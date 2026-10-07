import pytest

import demo_data
from models import PlayerInfo
from valuation import ValueModel, blended_ppg, fairness, games_remaining, ros_availability


def mk(pos="WR", games=4, total=40.0, proj=10.0, bye=0, status="ACTIVE", pid=1):
    return PlayerInfo(pid, f"P{pid}", pos, "XXX", status, "BE", [pos, "BE"], total_points=total,
                      games_played=games, season_proj_ppg=proj, bye_week=bye)


def test_blended_ppg_shrinks_toward_projection():
    p = mk(games=4, total=60.0, proj=10.0)             # actual 15 ppg, projection 10, K=4 -> halfway
    assert blended_ppg(p) == pytest.approx(12.5)
    assert blended_ppg(mk(games=0, total=0, proj=9.0)) == 9.0           # no games: projection only
    assert blended_ppg(mk(games=3, total=30, proj=0)) == 10.0           # no projection: actual only


def test_games_remaining_handles_bye():
    assert games_remaining(mk(bye=0), week=5, final_week=17) == 13       # unknown bye: no deduction
    assert games_remaining(mk(bye=9), week=5, final_week=17) == 12       # bye still ahead
    assert games_remaining(mk(bye=3), week=5, final_week=17) == 13       # bye already passed
    assert games_remaining(mk(bye=18), week=5, final_week=17) == 13      # bye after the season


def test_fairness_split():
    assert fairness(60, 40) == (60.0, 40.0)
    assert fairness(0, 0) == (50.0, 50.0)
    mine, theirs = fairness(30, 70)
    assert mine + theirs == pytest.approx(100.0) and mine == 30.0


def test_replacement_and_value_over_replacement():
    snap = demo_data.build_demo_snapshot()
    m = ValueModel(snap, demo_data.build_demo_free_agents())
    assert m.starters_by_pos["QB"] == 10                                  # 1 QB x 10 teams
    assert m.starters_by_pos["RB"] + m.starters_by_pos["WR"] + m.starters_by_pos["TE"] == 10 * 6   # 2 RB + 2 WR + 1 TE + 1 FLEX
    for pos, repl in m.replacement_ppg.items():
        best = max(m.ppg(p) for t in snap.teams for p in t.roster if p.position == pos)
        assert repl <= best
    stars = sorted((p for t in snap.teams for p in t.roster), key=m.value, reverse=True)
    assert m.value(stars[0]) > m.value(stars[-1]) >= 0.0


def test_injury_lowers_value_and_package_depth_discount():
    snap = demo_data.build_demo_snapshot()
    m = ValueModel(snap)
    p = snap.my_team.roster[0]
    healthy = m.value(p)
    p.injury_status = "INJURY_RESERVE"
    assert m.value(p) == pytest.approx(healthy * ros_availability(p) / 1.0)
    p.injury_status = "ACTIVE"
    a, b = sorted(snap.my_team.roster, key=m.value, reverse=True)[:2]
    assert m.package_value([a, b]) == pytest.approx(m.value(a) + 0.6 * m.value(b))
