import pytest

import demo_data
import trading as tr
from market import Market
from models import PlayerInfo
from season import Season
from strategy import Strategy
from valuation import ValueModel


def build(values=None, ppg=None):
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    for t in snap.teams:
        for p in t.roster:
            p.bye_week = 0
            if ppg and p.player_id in ppg:
                set_ppg(p, ppg[p.player_id])
    s = Season(snap, ValueModel(snap, fas), Strategy(), fas)
    m = Market(s, [p for t in snap.teams for p in t.roster] + fas)
    if values is not None:
        def row(p, _v=values, _m=m):
            r = type("R", (), {})()
            r.value, r.brand, r.components, r.has_market = _v.get(p.player_id, 15.0), 0.0, {}, True
            return r
        m.row = row
        m.value = lambda p, _v=values: _v.get(p.player_id, 15.0)
    return snap, s, m, tr.TradeWorld(snap, s, m, Strategy())


def set_ppg(p, ppg):
    p.week_proj, p.season_proj_ppg, p.total_points, p.games_played = ppg, ppg, ppg * 4, 4


def test_cheapest_winning_offer_prefers_one_for_one_over_two_for_one():
    snap, s, m, w = build()
    me, other = snap.my_team, snap.find_team("Kaden")
    target = next(p for p in other.roster if p.position == "WR")
    mine = [p for p in me.roster if p.position == "WR"][:3]
    values = {target.player_id: 50.0, mine[0].player_id: 48.0, mine[1].player_id: 30.0, mine[2].player_id: 30.0}
    snap, s, m, w = build(values, {target.player_id: 22.0, mine[0].player_id: 20.5})     # the target slightly out-scores what I give
    out = tr.search(w, tr.Constraints(partner=other.team_id, get_ids=[target.player_id], max_results=5))
    assert out, "a clearing 1-for-1 exists"
    top = [e for e in out if {p.player_id for p in e.get} == {target.player_id}][0]
    assert len(top.give) == 1 and top.acceptance.plausible          # the 1-for-1 clears, so no 2-for-1 is proposed for the same target
    assert all(len(e.give) == 1 for e in out if {p.player_id for p in e.get} == {target.player_id})


def test_no_sweetener_is_added_when_the_core_alone_clears():
    snap, s, m, w = build({})
    me, other = snap.my_team, snap.find_team("Kaden")
    a = next(p for p in me.roster if p.position == "WR")
    b = next(p for p in other.roster if p.position == "WR")
    snap, s, m, w = build({a.player_id: 60.0, b.player_id: 58.0}, {b.player_id: 20.0, a.player_id: 9.0})
    out = tr.search(w, tr.Constraints(partner=other.team_id, offering=[a.player_id], get_ids=[b.player_id]))
    assert out and [p.player_id for p in out[0].give] == [a.player_id] and not out[0].sweetener


def test_two_values_are_reported_separately_and_can_disagree():
    snap, s, m, w = build({})
    me, other = snap.my_team, snap.find_team("Kaden")
    a = next(p for p in me.roster if p.position == "WR")
    b = next(p for p in other.roster if p.position == "WR")
    snap, s, m, w = build({a.player_id: 70.0, b.player_id: 40.0}, {a.player_id: 25.0, b.player_id: 8.0})   # market loves what I give; he scores far less
    other = snap.find_team("Kaden")
    ev2 = tr.evaluate(w, other, [snap.my_team.roster[[p.player_id for p in snap.my_team.roster].index(a.player_id)]], [next(p for p in other.roster if p.player_id == b.player_id)])
    assert ev2.market_split_theirs > 60 and ev2.acceptance.plausible          # he'd happily accept ...
    assert ev2.verdict_me == "no"                                           # ... and it can still be bad for me


def test_ir_slot_player_costs_no_bench_spot_and_roster_overflow_cuts_worst():
    snap, s, m, w = build({})
    me, other = snap.my_team, snap.find_team("Kaden")
    cap = s.capacity
    while s.roster_count(me.roster) < cap:
        me.roster.append(PlayerInfo(9000 + len(me.roster), f"Filler{len(me.roster)}", "WR", "XXX", "ACTIVE", "BE", ["WR", "BE"], week_proj=2.0, total_points=8, games_played=4, season_proj_ppg=2.0))
    a, b1, b2 = next(p for p in me.roster if p.position == "WR"), other.roster[7], other.roster[8]
    ev = tr.evaluate(w, other, [a], [b1, b2])
    assert ev.my_drop is not None and ev.my_drop.player_id not in {b1.player_id, b2.player_id}
    assert any("cut" in n for n in ev.notes)
    ir = PlayerInfo(9999, "IRGuy", "WR", "XXX", "INJURY_RESERVE", "IR", ["WR", "BE", "IR"], week_proj=0, total_points=40, games_played=4, season_proj_ppg=15.0)
    before = s.roster_count(me.roster)
    me.roster.append(ir)
    assert s.roster_count(me.roster) == before                                  # the IR slot player isn't counted


def test_whole_league_scan_without_a_partner_can_return_any_team():
    snap, s, m, w = build({})
    out = tr.search(w, tr.Constraints(max_results=20))
    assert all(e.my_delta >= 0 for e in out)                                 # filter: nothing that hurts my lineup unless sell/rebuild
    assert len({e.other.team_id for e in out}) >= 1


def test_brown_for_wilson_regression_is_plausible_without_a_sweetener():
    """The calibration case: my injured star for his healthy WR. Market says my IR guy is worth more; the old tool needed an extra player."""
    snap, s, m, w = build({})
    me, other = snap.my_team, snap.find_team("Kaden")
    brown = next(p for p in me.roster if p.position == "WR")
    wilson = next(p for p in other.roster if p.position == "WR")
    brown.injury_status, brown.lineup_slot = "INJURY_RESERVE", "IR"
    snap, s, m, w = build({brown.player_id: 67.9, wilson.player_id: 59.2})
    ev = tr.evaluate(w, other, [brown], [wilson])
    assert ev.acceptance.plausible and ev.market_split_theirs > 50
    out = tr.search(w, tr.Constraints(partner=other.team_id, offering=[brown.player_id], get_ids=[wilson.player_id], allow_loss=True))
    assert out and [p.player_id for p in out[0].give] == [brown.player_id]    # straight up, nothing added


def test_ladder_has_open_step_and_never_exceeds_three_players():
    snap, s, m, w = build({})
    me, other = snap.my_team, snap.find_team("Kaden")
    a = next(p for p in me.roster if p.position == "WR"); b = next(p for p in other.roster if p.position == "WR")
    snap, s, m, w = build({a.player_id: 60.0, b.player_id: 58.0}, {b.player_id: 21.0, a.player_id: 9.0})
    out = tr.search(w, tr.Constraints(partner=other.team_id, get_ids=[b.player_id]))
    assert out and out[0].ladder[0].name == "Open"
    assert all(len(st.give) <= 3 for st in out[0].ladder)


def test_parse_request_and_pitch():
    snap, s, m, w = build({})
    other = snap.find_team("Kaden")
    text = f"Find a trade with Kaden at about 65/35 where I get a receiver and don't give up a running back, I need a WR for the playoffs"
    c = tr.parse_request(text, w)
    assert c.partner == other.team_id and c.target_split == 65.0 and "RB" in c.exclude_give_positions and c.need_position == "WR"
    assert c.summary() and c.notes
    ev = tr.evaluate(w, other, [snap.my_team.roster[7]], [other.roster[7]])
    msg = tr.pitch(w, ev)
    assert ev.give[0].name in msg and ev.get[0].name in msg and msg.startswith("Hey")


def test_large_model_vs_market_gap_is_flagged_speculative():
    snap, s, m, w = build({})
    me, other = snap.my_team, snap.find_team("Kaden")
    a = next(p for p in me.roster if p.position == "WR"); b = next(p for p in other.roster if p.position == "WR")
    snap, s, m, w = build({a.player_id: 40.0, b.player_id: 10.0}, {b.player_id: 26.0})
    other = snap.find_team("Kaden")
    ev = tr.evaluate(w, other, [next(p for p in snap.my_team.roster if p.player_id == a.player_id)], [next(p for p in other.roster if p.player_id == b.player_id)])
    assert ev.speculative and any("Speculative" in n for n in ev.notes)


def test_finder_respects_wanted_position_and_returns_valid_packages():
    snap, s, m, w = build({})
    other = snap.find_team("Kaden")
    out = tr.search(w, tr.Constraints(partner=other.team_id, want_positions={"WR"}, max_results=10))
    mine = {p.player_id for p in snap.my_team.roster}
    theirs = {p.player_id for p in other.roster}
    for e in out:
        assert all(p.position == "WR" for p in e.get)
        assert {p.player_id for p in e.give} <= mine and {p.player_id for p in e.get} <= theirs
        assert len(e.give) <= 3 and len(e.get) <= 2
