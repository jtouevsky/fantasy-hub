import itertools

import demo_data
from models import PlayerInfo
from optimizer import availability, best_lineup, expand_slots, plan_lineup

ELIG = demo_data.ELIGIBLE


def P(pid, pos, proj, slot="BE", status="ACTIVE", bye=False, extra=None):
    return PlayerInfo(pid, f"P{pid}", pos, "XXX", status, slot, ELIG[pos] + (extra or []) + ["BE"],
                      week_proj=proj, on_bye=bye)


def brute(players, starters):
    slots = expand_slots(starters)
    cands = [p for p in players if availability(p) > 0 or True]
    best = 0.0
    for combo in itertools.permutations(cands, len(slots)):
        if all(s in p.eligible_slots for s, p in zip(slots, combo)):
            best = max(best, sum(availability(p) for p in combo))
    return best


def test_bye_and_out_players_are_benched_and_swap_found():
    roster = [P(1, "QB", 0, "QB", bye=True), P(2, "QB", 14), P(3, "RB", 15, "RB"), P(4, "RB", 9, "RB"),
              P(5, "WR", 12, "WR"), P(6, "WR", 8, "WR", status="OUT"), P(7, "WR", 7), P(8, "TE", 9, "TE"),
              P(9, "RB", 6, "FLEX"), P(10, "D/ST", 5, "D/ST"), P(11, "K", 7, "K")]
    plan = plan_lineup(roster, demo_data.STARTERS)
    started = {p.player_id for _, p in plan.optimal if p}
    assert 2 in started and 1 not in started and 6 not in started
    assert any(s.player_in.player_id == 2 and s.player_out.player_id == 1 for s in plan.swaps)
    assert abs(plan.gain - sum(s.gain for s in plan.swaps)) < 0.11
    assert plan.optimal_total >= plan.current_total


def test_questionable_discount_changes_pick():
    roster = [P(1, "WR", 10, status="QUESTIONABLE"), P(2, "WR", 9.5), P(3, "WR", 1)]
    got = best_lineup(roster, {"WR": 1})
    assert got[0].player_id == 2        # 10*0.92 = 9.2 < 9.5


def test_matches_brute_force_with_overlapping_flex_slots():
    starters = {"RB": 1, "WR": 1, "RB/WR": 1, "FLEX": 1, "OP": 1}
    roster = [P(1, "RB", 12), P(2, "RB", 11), P(3, "WR", 13), P(4, "WR", 10), P(5, "TE", 9),
              P(6, "QB", 18), P(7, "WR", 8.5), P(8, "RB", 7)]
    got = best_lineup(roster, starters)
    assert abs(sum(availability(p) for p in got.values() if p) - brute(roster, starters)) < 1e-9


def test_demo_league_optimal_never_worse_than_current():
    snap = demo_data.build_demo_snapshot()
    for t in snap.teams:
        plan = plan_lineup(t.roster, snap.starter_slots)
        assert plan.optimal_total >= plan.current_total - 1e-9
