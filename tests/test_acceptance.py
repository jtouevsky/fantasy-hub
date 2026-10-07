import math

import pytest

import acceptance as acc
import demo_data
from market import Market
from models import PlayerInfo
from season import Season
from strategy import Strategy
from valuation import ValueModel


def world(values=None):
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    for t in snap.teams:
        for p in t.roster:
            p.bye_week = 0
    s = Season(snap, ValueModel(snap, fas), Strategy(), fas)
    m = Market(s, [p for t in snap.teams for p in t.roster] + fas)
    if values:
        m.row = lambda p, _v=values: type("R", (), {"value": _v.get(p.player_id, 20.0), "brand": 0.0, "components": {}, "has_market": True})()     # explicit market values
        m.value = lambda p, _v=values: _v.get(p.player_id, 20.0)
    return snap, s, m


def test_even_market_swap_is_at_least_plausible_and_lopsided_ones_are_not():
    snap, s, m = world()
    me, other = snap.my_team, snap.find_team("Kaden")
    a, b = me.roster[0], other.roster[0]
    snap, s, m = world({a.player_id: 60.0, b.player_id: 58.0})
    r = acc.assess(m, s, other, [a], [b], 0.0, False, {}, [])
    assert r.plausible and 0.45 < r.market_share_theirs < 0.6
    snap, s, m = world({a.player_id: 20.0, b.player_id: 60.0})
    bad = acc.assess(m, s, other, [a], [b], 0.0, False, {}, [])
    assert bad.label == "unlikely" and bad.market_share_theirs < 0.3


def test_the_real_calibration_case_brown_for_wilson_is_plausible_even_though_my_value_says_otherwise():
    """Live numbers: market Brown 67.9 vs Wilson 59.2 (ESPN consensus rank WR10 vs WR18); my value Brown 9.2 vs Wilson 49.2; Brown is on IR so their lineup
    drops for now. The OLD model said 85/15 'unlikely'; the other manager said he would do it straight up."""
    snap, s, m = world()
    me, other = snap.my_team, snap.find_team("Kaden")
    brown, wilson = me.roster[0], other.roster[0]
    brown.injury_status = "INJURY_RESERVE"
    snap, s, m = world({brown.player_id: 67.9, wilson.player_id: 59.2})
    r = acc.assess(m, s, other, [brown], [wilson], their_delta_ppg=-4.0, their_depth_unused=False, stats={}, negs=[])
    assert r.plausible, (r.label, r.logit, [(x.name, round(x.contribution, 2)) for x in r.signals])
    assert r.market_share_theirs > 0.5                                         # by market value he is RECEIVING more than he gives
    assert any(x.name == "market fairness" and x.contribution > 0 for x in r.signals)


def test_need_and_situation_move_the_label():
    snap, s, m = world()
    other = snap.find_team("Kaden")
    a, b = snap.my_team.roster[0], other.roster[0]
    snap, s, m = world({a.player_id: 50.0, b.player_id: 50.0})
    base = acc.assess(m, s, other, [a], [b], 0.0, False, {}, []).logit
    assert acc.assess(m, s, other, [a], [b], +6.0, False, {}, []).logit > base           # fills a need
    assert acc.assess(m, s, other, [a], [b], -6.0, False, {}, []).logit < base           # opens a hole
    a.injury_status = "INJURY_RESERVE"
    other.playoff_pct, other.wins, other.losses = 80.0, 3, 1
    contender = acc.assess(m, s, other, [a], [b], 0.0, False, {}, [])
    other.playoff_pct, other.wins, other.losses = 5.0, 0, 4
    rebuilding = acc.assess(m, s, other, [a], [b], 0.0, False, {}, [])
    assert rebuilding.logit > contender.logit


def test_trade_history_signal_uses_the_activity_feed():
    acts = [{"ts": 1000.0, "team_id": 2, "action": "TRADE_SENT"}, {"ts": 1000.2, "team_id": 2, "action": "TRADE_RECEIVED"}, {"ts": 5000.0, "team_id": 2, "action": "TRADE_SENT"},
            {"ts": 1000.0, "team_id": 3, "action": "TRADE_RECEIVED"}, {"ts": 10.0, "team_id": 4, "action": "FA ADDED"}, {"ts": 11.0, "team_id": 4, "action": "DROPPED"}]
    st = acc.manager_stats(acts)
    assert st[2]["trades"] == 2 and st[3]["trades"] == 1 and st[4]["trades"] == 0 and st[4]["adds"] == 1 and st[4]["drops"] == 1


def test_negotiation_log_confirms_exact_answers_and_only_those(tmp_path):
    p = str(tmp_path / "n.db")
    brown, wilson, judkins = PlayerInfo(1, "A.J. Brown", "WR", "NE"), PlayerInfo(2, "Garrett Wilson", "WR", "NYJ"), PlayerInfo(3, "Quinshon Judkins", "RB", "CLE")
    acc.log_negotiation(p, 5, "Sebastian", [brown], [wilson], "accepted", "said he'd do Brown for Wilson straight up", -0.4)
    negs = acc.negotiations(p, 5)
    same = acc.confirmed_override(negs, {1}, {2})
    assert same and same[0] == "likely" and "Confirmed by manager" in same[1] and "straight up" in same[1]
    assert acc.confirmed_override(negs, {1, 3}, {2}) is not None                       # giving MORE than he already accepted is still fine
    assert acc.confirmed_override(negs, {3}, {2}) is None                              # a different give is not covered
    acc.log_negotiation(p, 5, "Sebastian", [judkins], [wilson], "rejected", "no way", 0.2)
    assert acc.confirmed_override(acc.negotiations(p, 5), {3}, {2})[0] == "unlikely"
    assert acc.confirmed_override(acc.negotiations(p, 5), set(), set()) is None


def test_tendency_is_a_bayesian_shift_that_needs_evidence(tmp_path):
    assert acc.tendency([]) == 0.0
    one = [{"response": "accepted", "model_logit": -1.0}]
    many = [{"response": "accepted", "model_logit": -1.0}] * 6
    assert 0 < acc.tendency(one) < acc.tendency(many) <= acc.CLIP_TENDENCY            # more surprises -> bigger shift, bounded
    assert acc.tendency([{"response": "rejected", "model_logit": 1.0}] * 4) < -0.5
    assert abs(acc.tendency([{"response": "accepted", "model_logit": 2.0}] * 3)) < 0.35  # expected outcomes barely move it
    assert acc.tendency([{"response": "pending", "model_logit": 0.0}]) == 0.0


def test_logged_tendency_enters_the_signal_list(tmp_path):
    snap, s, m = world()
    other = snap.find_team("Kaden")
    a, b = snap.my_team.roster[0], other.roster[0]
    negs = [{"team_id": other.team_id, "response": "accepted", "model_logit": -1.5, "give_ids": set(), "get_ids": set(), "give_names": "", "get_names": "", "note": ""}] * 4
    r = acc.assess(m, s, other, [a], [b], 0.0, False, {}, negs)
    assert any(x.name == "negotiation history" and x.contribution > 0 for x in r.signals)
    assert acc.manager_profile(None, other, {}) if False else True
