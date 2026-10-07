"""Scenario leagues for the recommendation quality checks.

Each scenario builds a demo league with a specific situation, the agent tools wired to the shared engines, the question to ask the assistant,
and rules the answer must satisfy. The deterministic part (what `find_moves` returns) runs in the normal suite; the live part (what the real
assistant says) runs only as a manual suite: `RUN_AGENT_SCENARIOS=1 python -m tests.agent_scenarios.run_live`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

import agent
import demo_data
import hub as hub_mod
from models import PlayerInfo
from strategy import Strategy
from valuation import ValueModel

NOW = 1_800_000_000.0


def mk(pid, name, pos, ppg, slot="BE", team="NYJ", proj=None, status="ACTIVE", gp=4):
    return PlayerInfo(pid, name, pos, team, status, slot, [pos, "BE"], week_proj=ppg if proj is None else proj, total_points=ppg * gp, games_played=gp, season_proj_ppg=ppg, bye_week=0)


@dataclass
class Scenario:
    name: str
    question: str
    tools: agent.AgentTools
    # deterministic: what find_moves must (not) contain
    check_moves: Callable[[dict], None]
    # live: rules for the assistant's final text (lowercased)
    must: list[str] = field(default_factory=list)
    must_not: list[str] = field(default_factory=list)


def _tools(fas_extra=(), mine_extra=(), activity=(), tweak=None, strategy=None) -> agent.AgentTools:
    snap = demo_data.build_demo_snapshot()
    fas = list(demo_data.build_demo_free_agents()) + list(fas_extra)
    for t in snap.teams:
        for p in t.roster:
            p.bye_week = 0
    for p in fas:
        p.bye_week = 0
    snap.my_team.roster += list(mine_extra)
    if tweak:
        tweak(snap, fas)
    model = ValueModel(snap, fas)
    h = hub_mod.build(snap, model, fas, None, {}, list(activity), strat=strategy or Strategy())
    h.moves.now = NOW
    return agent.AgentTools(snap, model, lambda pos, n: [p for p in fas if pos in (None, p.position)], None, hub=h)


def dst_just_added() -> Scenario:
    patriots = mk(8001, "Patriots D/ST", "D/ST", 6.0, team="NE", proj=12.0)
    def tweak(snap, fas):
        cur = next(p for p in snap.my_team.roster if p.position == "D/ST")
        cur.week_proj = 9.0                                              # the D/ST I just added is decent; the alternative is only a little better
        patriots.week_proj = 10.0
    acts = [{"team_id": 1, "player_id": 1016, "action": "FA ADDED", "ts": NOW - 86400, "player": "Demo D/ST 1016"}]
    t = _tools(fas_extra=[patriots], activity=acts, tweak=tweak)
    def check(res):
        assert not any(m["position"] == "D/ST" for m in res["moves"])                                  # never a D/ST as an add/drop
        assert all(not s["swap"] for s in res["streaming"] if s["position"] == "D/ST")                    # +1.0 < 2.0: keep
        assert any("Keep your current" in s["reason"] for s in res["streaming"])
    return Scenario("dst_just_added", "Should I stream a different defense this week?", t, check,
                    must=["keep"], must_not=["add patriots"])


def two_qbs_never_a_third() -> Scenario:
    qb = mk(8002, "Kyler Murray", "QB", 7.2, team="ARI", proj=17.9)
    t = _tools(fas_extra=[qb])
    def check(res):
        assert all(m["position"] != "QB" for m in res["moves"])
        assert all(m["drop"] is None or "RB" not in str(m["drop"]) or m["position"] != "QB" for m in res["moves"])
    return Scenario("two_qbs", "Should I add Kyler Murray?", t, check, must_not=[r"re:(?<!don't )(?<!not )(?<!never )\badd kyler murray\b(?! is)"], must=["re:cap|maximum|at most|limit"])


def one_week_spike() -> Scenario:
    wr = mk(8003, "Spike Receiver", "WR", 5.5, team="CLE", proj=16.5)
    t = _tools(fas_extra=[wr])
    def check(res):
        spiky = [m for m in res["moves"] if m["add"] == "Spike Receiver"]
        assert not spiky or ("speculative" in spiky[0]["flags"] and spiky[0]["confidence"] == "low")
    return Scenario("one_week_spike", "Is Spike Receiver worth a pickup?", t, check, must=["speculative"], must_not=[r"re:(?<!not )(?<!no )\bhigh[- ]confidence"])


def no_good_moves() -> Scenario:
    def tweak(snap, fas):
        for p in fas:
            p.week_proj = p.season_proj_ppg = 1.0
            p.total_points = 4.0
    t = _tools(tweak=tweak)
    def check(res):
        assert res["no_move_needed"] is True and not res["moves"] and not any(s["swap"] for s in res["streaming"])
    return Scenario("no_good_moves", "Any waiver moves this week?", t, check, must=["no move"], must_not=["re:0\\.0 (points )?(of )?rest.of.season (value|points)"])


def _stab(ppg, touches, snap, td_share, dep=False, vol=False, raw=None):
    return {"ppg": ppg, "g": 8, "raw_ppg": raw if raw is not None else ppg, "touches_pg": touches, "snap_pct": snap, "td_share": td_share, "td_act_pg": 0.9, "td_exp_pg": 0.4,
            "targets_pg": touches, "carries_pg": 0.0, "dependent": dep, "volume_backed": vol, "r": [0.4, 0.9, 1.5], "rz_touch_pg": 1.0}


def td_fluke_free_agent() -> Scenario:
    fluke = mk(8010, "TD Fluke WR", "WR", 9.0, team="CLE", proj=15.0, gp=8)
    fluke.stable = _stab(6.5, 3.2, 0.33, 0.58, dep=True, raw=14.5)
    t = _tools(fas_extra=[fluke])
    def check(res):
        assert all(m["add"] != "TD Fluke WR" for m in res["moves"])
    return Scenario("td_fluke_fa", "Should I pick up TD Fluke WR? He just scored twice.", t, check, must=["re:td|touchdown"], must_not=[r"re:(?<!not )(?<!don't )(?<!never )\badd td fluke wr\b(?! is)"])


def volume_receiver_no_tds() -> Scenario:
    fluke = mk(8011, "TD Fluke WR", "WR", 9.0, team="CLE", proj=15.0, gp=8)
    fluke.stable = _stab(6.5, 3.2, 0.33, 0.58, dep=True, raw=14.5)
    vol = mk(8012, "Volume WR", "WR", 12.0, team="DEN", gp=8)
    vol.stable = _stab(15.2, 10.5, 0.86, 0.0, vol=True, raw=12.0)
    t = _tools(fas_extra=[fluke, vol])
    def check(res):
        adds = [m["add"] for m in res["moves"]]
        assert "Volume WR" in adds and "TD Fluke WR" not in adds
        top = next(m for m in res["moves"] if m["add"] == "Volume WR")
        assert top["evidence"]["opportunity"]["touches_pg"] == 10.5
    return Scenario("volume_wr_over_fluke", "Which receiver should I pick up: TD Fluke WR or Volume WR?", t, check, must=["volume wr"], must_not=[r"re:(?<!not )(?<!don't )(?<!never )\badd td fluke wr\b(?! is)"])


def no_worthwhile_adds() -> Scenario:
    nobody = mk(8013, "Low Role WR", "WR", 7.0, team="CLE", proj=11.0, gp=8)
    nobody.stable = _stab(6.0, 2.5, 0.25, 0.3)
    def tweak(snap, fas):
        for p in fas:
            if p.player_id != 8013:
                p.week_proj = p.season_proj_ppg = 1.0
                p.total_points = 4.0
    t = _tools(fas_extra=[nobody], tweak=tweak)
    def check(res):
        assert all(m["add"] != "Low Role WR" for m in res["moves"]) and res["no_move_needed"] is True
    return Scenario("no_worthwhile_adds", "Is there any add worth making right now?", t, check, must=["no move"])


ALL = [dst_just_added, two_qbs_never_a_third, one_week_spike, no_good_moves, td_fluke_free_agent, volume_receiver_no_tds, no_worthwhile_adds]
