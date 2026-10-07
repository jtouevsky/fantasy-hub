import pytest

import demo_data
import trades
from valuation import ValueModel, fairness


def _setup():
    snap = demo_data.build_demo_snapshot()
    model = ValueModel(snap, demo_data.build_demo_free_agents())
    return snap, model, snap.my_team, snap.find_team("Kaden")


def test_fairness_split_math():
    assert fairness(58, 42) == (58.0, 42.0)
    assert fairness(30, 10) == (75.0, 25.0)
    assert sum(fairness(7, 3)) == pytest.approx(100.0)


def test_swapping_equal_value_is_even_and_value_sides_are_consistent():
    snap, model, me, other = _setup()
    a = max(me.roster, key=model.value)
    mirror = max((p for p in other.roster if p.position == a.position), key=lambda p: -abs(model.value(p) - model.value(a)))
    ev = trades.evaluate_trade(snap, model, other, [a], [mirror])
    assert ev.my_share + ev.their_share == pytest.approx(100.0, abs=0.2)
    expected_mine, _ = fairness(model.value(mirror), model.value(a))
    assert ev.my_share == pytest.approx(expected_mine)
    ev2 = trades.evaluate_trade(snap, model, other, [a], [mirror])
    assert ev2.my_share == ev.my_share


def test_evaluate_rejects_players_not_on_the_right_rosters():
    snap, model, me, other = _setup()
    with pytest.raises(ValueError):
        trades.evaluate_trade(snap, model, other, [other.roster[0]], [other.roster[1]])
    with pytest.raises(ValueError):
        trades.evaluate_trade(snap, model, other, [me.roster[0]], [me.roster[1]])


def test_lineup_impact_fills_holes_with_replacement_level_players():
    snap, model, me, other = _setup()
    only_te = [p for p in me.roster if p.position == "TE"]
    star_te = max(only_te, key=model.value)
    ev = trades.evaluate_trade(snap, model, other, [star_te], [max(other.roster, key=model.value)])
    assert all(not n.startswith("a replacement") for n in ev.mine.now_starting)   # phantoms never listed as players


def test_lopsided_trades_are_penalized_vs_target():
    snap, model, me, other = _setup()
    star = max(me.roster, key=model.value)
    mid = sorted(me.roster, key=model.value)[len(me.roster) // 2]
    fair = trades.evaluate_trade(snap, model, other, [star], [max(other.roster, key=model.value)])
    robbery = trades.evaluate_trade(snap, model, other, [mid], [max(other.roster, key=model.value)])
    robbery.my_share = 85.0
    fair.my_share = 60.0
    assert trades._score(robbery, 60.0) < trades._score(fair, 60.0)


def test_their_lineup_improvement_ranks_higher_all_else_equal():
    snap, model, me, other = _setup()
    base = trades.evaluate_trade(snap, model, other, [me.roster[0]], [other.roster[0]])
    good, bad = _clone(base, theirs_delta=+2.0), _clone(base, theirs_delta=-2.0)
    assert trades._score(good, 60.0) > trades._score(bad, 60.0)


def _clone(ev, theirs_delta):
    import copy
    e = copy.deepcopy(ev)
    e.my_share, e.their_share = 60.0, 40.0
    e.theirs.after_ppg = e.theirs.before_ppg + theirs_delta
    e.acceptance = trades._acceptance(40.0, theirs_delta)
    return e


def test_finder_returns_ranked_valid_packages_of_all_shapes():
    snap, model, me, other = _setup()
    offer = max(me.roster, key=model.value)
    res = trades.find_trades(snap, model, other, [offer], target_split=55, max_results=50)
    assert res and [r.score for r in res] == sorted((r.score for r in res), reverse=True)
    my_ids, their_ids = {p.player_id for p in me.roster}, {p.player_id for p in other.roster}
    for r in res:
        assert offer.player_id in {p.player_id for p in r.give}
        assert {p.player_id for p in r.give} <= my_ids and {p.player_id for p in r.get} <= their_ids
        assert r.my_share >= trades.MIN_MY_SHARE and abs(r.my_share - 55) <= trades.PREFILTER_WINDOW + 0.1
    assert {"1-for-1"} <= {r.kind for r in res}


def test_finder_respects_wanted_position():
    snap, model, me, other = _setup()
    offer = max((p for p in me.roster if p.position == "RB"), key=model.value)
    res = trades.find_trades(snap, model, other, [offer], 60, {"WR"}, max_results=30)
    assert res and all(any(p.position == "WR" for p in r.get) for r in res)


def test_describe_is_plain_english_and_ends_with_espn_action():
    snap, model, me, other = _setup()
    ev = trades.evaluate_trade(snap, model, other, [me.roster[0]], [other.roster[0]])
    text = trades.describe(ev)
    assert "You give" in text and "ESPN app" in text and "/" in text


def test_find_team_by_owner_first_name():
    snap, *_ = _setup()
    assert snap.find_team("kaden").team_id == 2
    with pytest.raises(LookupError):
        snap.find_team("nobody")
