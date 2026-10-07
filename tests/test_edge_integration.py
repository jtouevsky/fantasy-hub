import dataclasses

import demo_data
import trading
import moves
from season import Season
from strategy import Strategy
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


def test_ros_edge_flows_into_value_model_and_buy_low_tag_shows_in_trade_notes():
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    model0 = ValueModel(snap, fas)
    other = snap.find_team("Kaden")
    get = max(other.roster, key=model0.value)
    give = max(snap.my_team.roster, key=model0.value)
    v_before = model0.value(get)
    _apply(other.roster, {}, ros={get.player_id: 2.0}, tags={get.player_id: [("buy low", "x")]})
    model1 = ValueModel(snap, fas)
    assert model1.value(get) > v_before                                                           # +2 pts/game rest of season raises value
    world = trading.make_world(snap, fas, model1, Strategy(), {})
    ev = trading.evaluate(world, other, [give], [get])
    assert any("BUY LOW" in n for n in ev.notes)


def test_sell_high_tags_show_up_on_both_sides_of_a_trade():
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    model = ValueModel(snap, fas)
    other = snap.find_team("Kaden")
    give, get = snap.my_team.roster[0], other.roster[0]
    give.tags = [["sell high", "x"]]
    world = trading.make_world(snap, fas, model, Strategy(), {})
    assert any("good timing to move him" in n for n in trading.evaluate(world, other, [give], [get]).notes)
    give.tags, get.tags = [], [["sell high", "x"]]
    assert any("expect a fade" in n for n in trading.evaluate(world, other, [give], [get]).notes)


def test_move_reason_cites_the_edge_explanation():
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    for t in snap.teams:
        for p in t.roster:
            p.bye_week = 0
    star = max((p for p in fas if p.position == "RB"), key=lambda p: p.week_proj)
    star.bye_week = 0
    star.week_proj = star.week_proj + 8
    star.espn_week_proj = star.week_proj - 8
    star.edge = [{"type": "cascade", "delta": 8.0, "reason": "RB1 on IR, he's next up", "source": "x", "confidence": "med", "at": 0}]
    star.tags = [["buy low", "t"]]
    model = ValueModel(snap, fas)
    st = Strategy()
    eng = moves.MoveEngine(snap, Season(snap, model, st, fas), st, fas)
    ms = eng.find_moves()
    mine = [m for m in ms.moves if m.add.player_id == star.player_id]
    assert mine and "RB1 on IR, he's next up" in mine[0].reason
