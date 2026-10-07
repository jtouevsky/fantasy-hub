import dataclasses

import demo_data
import trades
import waivers
from edge import apply as eapply
from edge.engine import EngineResult
from edge.types import Adjustment, AdjustedProjection
from models import PlayerInfo
from optimizer import plan_lineup
from valuation import ValueModel


def _adj(pid, delta, reason="RB1 out, he's next up", typ="cascade"):
    return Adjustment(pid, 2026, 5, typ, delta, reason, "nflverse", "med")


def _apply(players, deltas, ros=None, tags=None):
    res = EngineResult(2026, 5, 0.0)
    res.projections = {pid: AdjustedProjection(pid, 2026, 5, next(p.week_proj for p in players if p.player_id == pid), [_adj(pid, d)]) for pid, d in deltas.items()}
    res.ros, res.tags = ros or {}, tags or {}
    eapply.apply_result(players, res)


def test_edge_can_flip_a_start_sit_and_the_swap_is_labeled_as_an_edge():
    snap = demo_data.build_demo_snapshot()
    roster = snap.my_team.roster
    starter = next(p for p in roster if p.lineup_slot == "WR")
    bench = next(p for p in sorted((p for p in roster if p.position == "WR" and p.lineup_slot == "BE"), key=lambda p: p.week_proj))
    gap = starter.week_proj - bench.week_proj
    base_plan = plan_lineup(roster, snap.starter_slots)
    assert not any(s.player_in.player_id == bench.player_id for s in base_plan.swaps)              # on ESPN's numbers he isn't a swap
    _apply(roster, {bench.player_id: gap + 3.0})
    plan = plan_lineup(roster, snap.starter_slots)
    sw = next(s for s in plan.swaps if s.player_in.player_id == bench.player_id)
    assert sw.from_edge and "Edge:" in sw.edge_note and sw.espn_gain == 0.0
    assert plan.espn_optimal_total <= plan.optimal_total - 2.0                                    # totals reported both ways


def test_swaps_that_exist_on_espn_numbers_are_not_labeled_edge():
    roster = [PlayerInfo(1, "Young", "QB", "CAR", "ACTIVE", "QB", ["QB", "BE"], week_proj=0.0, on_bye=True), PlayerInfo(2, "Herbert", "QB", "LAC", "ACTIVE", "BE", ["QB", "BE"], week_proj=13.9)]
    _apply(roster, {2: 0.5})
    plan = plan_lineup(roster, {"QB": 1})
    assert plan.swaps and plan.swaps[0].from_edge is False                                        # the bye swap is true regardless of edges


def test_ros_edge_flows_into_value_model_and_trade_tags_tilt_the_score():
    snap = demo_data.build_demo_snapshot()
    model0 = ValueModel(snap, demo_data.build_demo_free_agents())
    other = snap.find_team("Kaden")
    get = max(other.roster, key=model0.value)
    give = max(snap.my_team.roster, key=model0.value)
    v_before = model0.value(get)
    ev0 = trades.evaluate_trade(snap, model0, other, [give], [get])
    _apply(other.roster, {}, ros={get.player_id: 2.0}, tags={get.player_id: [("buy low", "x")]})
    model1 = ValueModel(snap, demo_data.build_demo_free_agents())
    assert model1.value(get) > v_before                                                           # +2 pts/game rest of season raises value
    ev1 = trades.evaluate_trade(snap, model1, other, [give], [get])
    assert ev1.tag_tilt == trades.TAG_TILT and any("BUY LOW" in n for n in ev1.notes)
    assert ev0.tag_tilt == 0.0


def test_sell_high_player_given_away_scores_better_and_received_scores_worse():
    snap = demo_data.build_demo_snapshot()
    model = ValueModel(snap, demo_data.build_demo_free_agents())
    other = snap.find_team("Kaden")
    give, get = snap.my_team.roster[0], other.roster[0]
    base = trades.evaluate_trade(snap, model, other, [give], [get]).score
    give.tags = [["sell high", "x"]]
    assert trades.evaluate_trade(snap, model, other, [give], [get]).score == base + trades.TAG_TILT
    give.tags, get.tags = [], [["sell high", "x"]]
    assert trades.evaluate_trade(snap, model, other, [give], [get]).score == base - trades.TAG_TILT


def test_waiver_reason_leads_with_the_edge_explanation():
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    star = max((p for p in fas if p.position == "RB"), key=lambda p: p.week_proj)
    star.week_proj = star.week_proj + 8
    star.espn_week_proj = star.week_proj - 8
    star.edge = [{"type": "cascade", "delta": 8.0, "reason": "RB1 on IR, he's next up", "source": "x", "confidence": "med", "at": 0}]
    star.tags = [["buy low", "t"]]
    model = ValueModel(snap, fas)
    sugg = waivers.suggest_add_drops(snap, model, fas)
    mine = [s for s in sugg if s.add.player_id == star.player_id]
    assert mine and mine[0].reason.startswith("Edge: RB1 on IR, he's next up")
    ranks = waivers.rank_free_agents(model, fas)
    assert next(r for r in ranks if r.player.player_id == star.player_id).tags == ("buy low",)
