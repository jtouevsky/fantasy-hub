"""Claude-powered chat agent with tool use. Every number it states must come from a tool result.

Read-only: no tool can change anything on ESPN; every recommendation ends with an ESPN-app action for you.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import db
import news as news_mod
import trades as trades_mod
import waivers as waivers_mod
import assets
from ui import EDGE_LABEL
from models import LeagueSnapshot, PlayerInfo
from optimizer import plan_lineup
from sleeper import SleeperIndex
from valuation import ValueModel

MAX_TOOL_ROUNDS = 10
RECOMMENDATION_TOOLS = {"find_trades": "trade", "evaluate_trade": "trade", "optimize_lineup": "lineup",
                        "suggest_waiver_moves": "waiver"}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def _r(x: float, n: int = 1) -> float:
    return round(float(x), n)


class AgentTools:
    def __init__(self, snap: LeagueSnapshot, model: ValueModel,
                 fetch_free_agents: Callable[[Optional[str], int], list[PlayerInfo]],
                 fetch_news: Optional[Callable[[int, int], list[dict]]] = None,
                 sleeper_index: Optional[SleeperIndex] = None, trending: Optional[dict[str, int]] = None,
                 db_path: Optional[str] = None, edge=None, events: Optional[list] = None):
        self.edge, self.events = edge, events or []
        self.snap, self.model = snap, model
        self.fetch_free_agents, self.fetch_news = fetch_free_agents, fetch_news
        self.index, self.trending, self.db_path = sleeper_index, trending or {}, db_path
        self.logged_explicitly = False

    # ---- helpers ---------------------------------------------------------
    def _player_row(self, p: PlayerInfo) -> dict:
        return {
            "name": p.name, "position": p.position, "nfl_team": p.pro_team, "lineup_slot": p.lineup_slot,
            "injury_status": p.injury_status, "on_bye_this_week": p.on_bye, "bye_week": p.bye_week or None,
            "projected_points_this_week": _r(p.week_proj), "points_per_game_so_far": _r(p.actual_ppg),
            "rest_of_season_value": _r(self.model.value(p), 0),
            **({"espn_projection": _r(p.espn_week_proj), "edge_adjustment": _r(p.edge_total), "tags": [t[0] for t in p.tags]} if p.has_edge or p.tags else {}),
        }

    def _team_row(self, t) -> dict:
        return {"team_name": t.name, "owner": t.owner_label, "record": t.record, "standing": t.standing,
                "points_for": _r(t.points_for), "players": [self._player_row(p) for p in sorted(
                    t.roster, key=lambda p: -self.model.value(p))]}

    def _all_players(self) -> list[PlayerInfo]:
        return [p for t in self.snap.teams for p in t.roster]

    def _resolve_mine(self, names: list[str]) -> list[PlayerInfo]:
        return [self.snap.find_player(n, self.snap.my_team) for n in names]

    # ---- tool implementations ---------------------------------------------
    def get_my_roster(self) -> dict:
        return self._team_row(self.snap.my_team)

    def get_team_roster(self, team_name_or_owner: str) -> dict:
        return self._team_row(self.snap.find_team(team_name_or_owner))

    def get_league_overview(self) -> dict:
        me = self.snap.my_team
        m = self.snap.matchup_for(me.team_id)
        opp = self.snap.team(m.opponent_of(me.team_id)) if m else None
        mine_home = m and m.home_team_id == me.team_id
        return {
            "league": self.snap.league_name, "week": self.snap.week, "my_team": me.name, "my_record": me.record,
            "starting_lineup_slots": self.snap.starter_slots, "bench_spots": self.snap.bench_slots,
            "scoring": self.snap.scoring_notes,
            "this_week_matchup": None if not (m and opp) else {
                "opponent_team": opp.name, "opponent_owner": opp.owner_label,
                "my_projected": _r(m.home_proj if mine_home else m.away_proj),
                "opponent_projected": _r(m.away_proj if mine_home else m.home_proj)},
            "standings": [{"rank": t.standing, "team": t.name, "owner": t.owner_label, "record": t.record,
                           "points_for": _r(t.points_for)} for t in self.snap.standings()],
        }

    def get_free_agents(self, position: Optional[str] = None, limit: int = 12) -> dict:
        positions = [position] if position else sorted({p for p in ("QB", "RB", "WR", "TE", "K", "D/ST")
                                                        if p in self.snap.starter_slots or p in ("RB", "WR", "TE")})
        fas = [p for pos in positions for p in self.fetch_free_agents(pos, 30)]
        ranks = waivers_mod.rank_free_agents(self.model, fas, self.index, self.trending)
        ranks.sort(key=lambda r: (-r.ros_value, -r.week_value))
        return {"free_agents": [{
            **self._player_row(r.player), "this_week_value": _r(r.week_value), "percent_owned": r.player.percent_owned,
            "sleeper_trending_adds_24h": r.trending_adds or None, "breakout_flag": r.breakout,
        } for r in ranks[:max(1, min(limit, 30))]]}

    def evaluate_trade(self, give: list[str], get: list[str], team_name_or_owner: Optional[str] = None) -> dict:
        give_p = self._resolve_mine(give)
        if team_name_or_owner:
            other = self.snap.find_team(team_name_or_owner)
            get_p = [self.snap.find_player(n, other) for n in get]
        else:
            get_p = [self.snap.find_player(n) for n in get]
            owners = {p.owner_team_id for p in get_p}
            if len(owners) != 1 or None in owners:
                raise LookupError("All players you want must be on the same other team; pass team_name_or_owner.")
            other = self.snap.team(owners.pop())
        ev = trades_mod.evaluate_trade(self.snap, self.model, other, give_p, get_p)
        return self._trade_row(ev)

    def find_trades(self, target_team: str, offering: list[str], target_split: float = 60,
                    want_positions: Optional[list[str]] = None, max_results: int = 5) -> dict:
        other = self.snap.find_team(target_team)
        offer = self._resolve_mine(offering)
        found = trades_mod.find_trades(self.snap, self.model, other, offer, float(target_split),
                                       {w.upper() for w in want_positions} if want_positions else None,
                                       max(1, min(max_results, 8)))
        return {"target_team": other.name, "owner": other.owner_label, "target_split_for_me": target_split,
                "n_found": len(found), "trades": [self._trade_row(e) for e in found],
                "note": "Split = share of combined value I get. Acceptance = how likely the other manager says yes."}

    def _trade_row(self, ev: trades_mod.TradeEval) -> dict:
        imp = lambda i: {"weekly_points_change": _r(i.delta), "would_start": i.now_starting,
                         "moved_to_bench": i.no_longer_starting, "needs_free_pickup_at": i.pickups_needed}
        return {
            "type": ev.kind, "other_team": ev.other_team, "i_give": [self._player_row(p) for p in ev.give],
            "i_get": [self._player_row(p) for p in ev.get], "value_i_get": _r(ev.value_get, 0), "value_i_give": _r(ev.value_give, 0),
            "split_me_vs_them": f"{ev.my_share:.0f}/{ev.their_share:.0f}", "other_manager_acceptance": ev.acceptance,
            "my_lineup": imp(ev.mine), "their_lineup": imp(ev.theirs), "notes": ev.notes, "ranking_score": ev.score,
            "espn_action": f"Open {ev.other_team}'s team in the ESPN app and propose this trade.",
        }

    def optimize_lineup(self) -> dict:
        plan = plan_lineup(self.snap.my_team.roster, self.snap.starter_slots)
        row = lambda rows: [{"slot": s, "player": p.name if p else None, "projected": _r(p.week_proj) if p else 0,
                             "injury_status": p.injury_status if p else None} for s, p in rows]
        return {"current_lineup": row(plan.current), "optimal_lineup": row(plan.optimal),
                "current_projected_total": plan.current_total, "optimal_projected_total": plan.optimal_total,
                "gain": _r(plan.gain), "swaps": [{"gain": s.gain, "action": s.action(), "reason": s.reason} for s in plan.swaps],
                "warnings": plan.warnings}

    def suggest_waiver_moves(self, max_results: int = 5) -> dict:
        positions = ["QB", "RB", "WR", "TE", "D/ST", "K"]
        fas = [p for pos in positions if pos in self.snap.starter_slots or pos in ("RB", "WR", "TE")
               for p in self.fetch_free_agents(pos, 30)]
        sugg = waivers_mod.suggest_add_drops(self.snap, self.model, fas, self.index, self.trending, max_results)
        return {"suggestions": [{
            "add": self._player_row(s.add), "drop": s.drop.name, "points_per_week_gain_rest_of_season": s.ppg_gain,
            "points_gain_this_week": s.weekly_gain, "sleeper_trending_adds_24h": s.trending_adds or None,
            "reason": s.reason, "espn_action": s.action()} for s in sugg]}

    def get_player_news(self, player: str) -> dict:
        if self.fetch_news is None:
            raise LookupError("Player news isn't available in this mode.")
        try:
            p = self.snap.find_player(player)
        except LookupError:
            fas = [x for pos in ("QB", "RB", "WR", "TE", "D/ST") for x in self.fetch_free_agents(pos, 30)]
            q = player.lower()
            hits = [x for x in fas if q in x.name.lower()]
            if len(hits) != 1:
                raise LookupError(f"Couldn't uniquely find player '{player}' on any roster or the free-agent list.")
            p = hits[0]
        pn = news_mod.get_player_news(p, self.fetch_news, self.index, db_path=self.db_path)
        return {"player": self._player_row(p), "sleeper_injury": pn.sleeper or None,
                "news": [{"headline": i.headline, "detail": i.story[:400], "published": i.published, "source": i.source}
                         for i in pn.items[:5]]}

    # ---- edge engine tools ------------------------------------------------------
    def _need_edge(self):
        if self.edge is None:
            raise LookupError("The edge engine isn't running (demo data, or it failed to load), so there are no adjustments - only ESPN's projections.")
        return self.edge

    def _edge_row(self, p: PlayerInfo) -> dict:
        return {"name": p.name, "position": p.position, "nfl_team": p.pro_team, "espn_projection": _r(p.espn_week_proj or p.week_proj),
                "adjusted_projection": _r(p.week_proj), "total_adjustment": _r(p.edge_total),
                "adjustments": [{"type": a["type"], "label": EDGE_LABEL.get(a["type"], a["type"]), "points": _r(a["delta"]), "uncapped_points": _r(a.get("raw", a["delta"])),
                                 "reason": a["reason"], "source": a["source"], "confidence": a["confidence"]} for a in sorted(p.edge, key=lambda a: -abs(a["delta"]))],
                "tags": [{"tag": t[0], "explanation": t[1]} for t in p.tags], "rest_of_season_edge_points_per_game": _r(p.edge_ros, 2),
                "note": "" if p.edge else "No adjustment: no edge data cleared the noise threshold, or data was missing. ESPN's number is used as is."}

    def get_edges(self, player_or_team: str, week: Optional[int] = None) -> dict:
        """Adjustments (ESPN -> adjusted) for one player, a fantasy team's roster, or an NFL team's players, with sources and confidence."""
        e = self._need_edge()
        if week is not None and week != self.snap.week:
            raise ValueError(f"Edges are only computed for the current week ({self.snap.week}).")
        try:
            return {"week": self.snap.week, "players": [self._edge_row(self.snap.find_player(player_or_team))]}
        except LookupError as player_err:
            try:
                t = self.snap.find_team(player_or_team)
                ps = sorted(t.roster, key=lambda p: -abs(p.edge_total))
                return {"week": self.snap.week, "fantasy_team": t.name, "players": [self._edge_row(p) for p in ps if p.has_edge or p.tags][:12],
                        "note": "Only players with an adjustment or tag are listed; everyone else uses ESPN's number as is."}
            except LookupError:
                abbr = self._nfl_abbr(player_or_team)
                if not abbr:
                    raise player_err
                ps = [p for p in self._all_players() if p.pro_team == abbr and (p.has_edge or p.tags)]
                return {"week": self.snap.week, "nfl_team": abbr, "players": [self._edge_row(p) for p in sorted(ps, key=lambda p: -abs(p.edge_total))][:12]}

    def _nfl_abbr(self, q: str) -> Optional[str]:
        ql = q.strip().lower()
        for ab, t in assets.nfl_teams(self.db_path).items():
            if ql in (ab.lower(), t.name.lower(), t.short.lower()):
                return ab
        return None

    def get_injury_cascade(self, team: str) -> dict:
        """Who is out/questionable on an NFL team, and who inherits the carries/targets (with points and confidence)."""
        e = self._need_edge()
        abbr = self._nfl_abbr(team) or team.upper()
        c = next((c for c in e.cascades if c["team"] == abbr), None)
        if not c:
            return {"nfl_team": abbr, "cascade": None, "note": f"No skill-position absences are creating an opportunity shift for {abbr} this week (or the data wasn't available)."}
        return {"nfl_team": abbr, "absent": c["absent"], "beneficiaries": sorted(c["beneficiaries"], key=lambda b: -abs(b["weekly_pts"]))[:8],
                "note": "weekly_pts = estimated change in that player's fantasy points from the shifted opportunity (already scaled by the backtest calibration)."}

    def get_buy_low_sell_high(self) -> dict:
        """Players tagged buy-low / sell-high (expected points vs actual production, last 4 games) across my roster, other teams and free agents."""
        self._need_edge()
        out = {"buy_low": [], "sell_high": [], "role_growing": []}
        key = {"buy low": "buy_low", "sell high": "sell_high", "role growing": "role_growing"}
        owners = {p.player_id: t for t in self.snap.teams for p in t.roster}
        for p in list(self._all_players()) + list(self._fas()):
            for tag, why in p.tags:
                t = owners.get(p.player_id)
                out[key[tag]].append({"name": p.name, "position": p.position, "nfl_team": p.pro_team, "on": ("my team" if t and t.team_id == self.snap.my_team_id else t.name if t else "free agent"),
                                      "why": why, "rest_of_season_value": _r(self.model.value(p), 0)})
        for k in out:
            out[k] = sorted(out[k], key=lambda r: -r["rest_of_season_value"])[:10]
        out["note"] = ("Backtest (2025): buy-low players beat their baseline by ~2 points the next game, sell-high players fell short by ~4. "
                       "'Role growing' was NOT predictive on its own - treat it as context only.")
        return out

    def _fas(self) -> list:
        try:
            return [p for pos in ("QB", "RB", "WR", "TE") for p in self.fetch_free_agents(pos, 30)]
        except Exception:
            return []

    def get_game_environment(self, game: str) -> dict:
        """Vegas line/total/implied points and weather (with forecast timestamp) for a game: 'KC', 'KC vs BUF', or a team name."""
        e = self._need_edge()
        abbrs = []
        for tok in re.split(r"\s+(?:vs\.?|@|at|v)\s+|,|/|\s{2,}", game.strip(), flags=re.I):
            ab = self._nfl_abbr(tok) or (tok.strip().upper() if tok.strip().upper() in e.game_env else None)
            if ab:
                abbrs.append(ab)
        if not abbrs:
            raise LookupError(f"Couldn't find a team in '{game}'. Use an NFL team name or abbreviation, e.g. 'KC' or 'KC vs BUF'.")
        env = e.game_env.get(abbrs[0])
        if env is None:
            return {"team": abbrs[0], "note": "No game this week (bye) or schedule data unavailable."}
        import datetime as _dt
        return {"game": f"{env.team} vs {env.opp}", "kickoff_et": env.kickoff, "spread_for_" + env.team: env.spread, "total": env.total, "implied_" + env.team: env.implied, "implied_" + env.opp: env.opp_implied,
                "lines_source": env.lines_source, "stadium": env.stadium, "roof": env.roof, "wind_mph": env.wind_mph, "temp_f": env.temp_f, "precip_probability_pct": env.precip_prob,
                "weather_note": env.weather_note, "forecast_as_of": _dt.datetime.fromtimestamp(env.forecast_at).isoformat(timespec="minutes") if env.forecast_at and env.wind_mph is not None else None,
                "positive_spread_means": f"{env.team} favored"}

    def log_recommendation(self, kind: str, summary: str, details: Optional[dict] = None) -> dict:
        rid = db.log_recommendation(kind, summary, details, self.snap.week, "agent", self.db_path)
        self.logged_explicitly = True
        return {"logged": True, "id": rid}

    # ---- dispatch ------------------------------------------------------------
    def call(self, name: str, args: dict) -> tuple[Any, bool]:
        """Returns (result, is_error)."""
        fn = getattr(self, name, None)
        if name.startswith("_") or name not in TOOL_NAMES or fn is None:
            return {"error": f"Unknown tool {name}"}, True
        try:
            return fn(**(args or {})), False
        except (LookupError, ValueError, TypeError) as e:
            return {"error": str(e)}, True


_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}
TOOLS: list[dict] = [
    {"name": "get_league_overview", "description": "League settings, my record, this week's matchup with projections, and standings.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_my_roster", "description": "My players with lineup slot, injury status, bye, this-week projection, season PPG and rest-of-season value.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_team_roster", "description": "Another team's roster. Accepts the owner's first name (e.g. 'Kaden'), full name, or team name.",
     "input_schema": {"type": "object", "properties": {"team_name_or_owner": _STR}, "required": ["team_name_or_owner"]}},
    {"name": "get_free_agents", "description": "Best available free agents ranked by rest-of-season value, with Sleeper trending adds. Optionally filter by position (QB/RB/WR/TE/D/ST/K).",
     "input_schema": {"type": "object", "properties": {"position": _STR, "limit": {"type": "integer"}}}},
    {"name": "evaluate_trade", "description": "Evaluate a specific trade: value each side gets, the fairness split, and how each team's starting lineup changes. 'give' = my players, 'get' = their players.",
     "input_schema": {"type": "object", "properties": {"give": _STRS, "get": _STRS, "team_name_or_owner": _STR}, "required": ["give", "get"]}},
    {"name": "find_trades", "description": "Search 1-for-1, 2-for-1 and 1-for-2 packages with a target team that include my offered player(s). target_split is MY share of the value (60 = slightly in my favor). Favors deals the other manager would accept.",
     "input_schema": {"type": "object", "properties": {"target_team": _STR, "offering": _STRS, "target_split": {"type": "number"},
                                                        "want_positions": _STRS, "max_results": {"type": "integer"}},
                      "required": ["target_team", "offering"]}},
    {"name": "optimize_lineup", "description": "Best starting lineup for this week vs my current lineup, with each swap's projected gain.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "suggest_waiver_moves", "description": "Specific add/drop suggestions from the waiver wire with projected gains.",
     "input_schema": {"type": "object", "properties": {"max_results": {"type": "integer"}}}},
    {"name": "get_player_news", "description": "Recent ESPN news and Sleeper injury details for one player.",
     "input_schema": {"type": "object", "properties": {"player": _STR}, "required": ["player"]}},
    {"name": "get_edges", "description": "The edge engine's adjustments on top of ESPN's projection (ESPN -> adjusted), each with plain-English reason, source, confidence and the uncapped size. Pass a player name, a fantasy team/owner (e.g. 'Kaden'), or an NFL team (e.g. 'KC'). week defaults to the current week.",
     "input_schema": {"type": "object", "properties": {"player_or_team": _STR, "week": {"type": "integer"}}, "required": ["player_or_team"]}},
    {"name": "get_injury_cascade", "description": "For an NFL team: which skill players are out/questionable and who picks up their carries and targets, with estimated points and confidence.",
     "input_schema": {"type": "object", "properties": {"team": _STR}, "required": ["team"]}},
    {"name": "get_buy_low_sell_high", "description": "Players tagged buy-low / sell-high (expected fantasy points vs actual production over 4 games) on my team, other teams and the waiver wire. Use for trades and waivers.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_game_environment", "description": "Vegas spread/total/implied points and weather (with forecast timestamp) for a game. Pass 'KC', 'KC vs BUF' or a team name.",
     "input_schema": {"type": "object", "properties": {"game": _STR}, "required": ["game"]}},
    {"name": "log_recommendation", "description": "Record a concrete recommendation you are making (so the user can later check whether it was good). Call once per distinct recommendation.",
     "input_schema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["trade", "lineup", "waiver", "news"]},
                                                        "summary": _STR, "details": {"type": "object"}}, "required": ["kind", "summary"]}},
]
TOOL_NAMES = {t["name"] for t in TOOLS}


# ---------------------------------------------------------------------------
# System prompt + loop
# ---------------------------------------------------------------------------
def system_prompt(snap: LeagueSnapshot) -> str:
    me = snap.my_team
    return f"""You are a fantasy football assistant for one person who is new to football and plays in an ESPN league. They want you to do the thinking for them.

League: {snap.league_name}. It is week {snap.week} of the {snap.year} season. Their team is "{me.name}" (owner {me.owner_label}), record {me.record}.
Starting slots: {', '.join(f'{n}x {s}' for s, n in snap.starter_slots.items())}; {snap.bench_slots} bench spots. Scoring: {snap.scoring_notes}.

Rules you must follow:
1. NEVER state a stat, projection, value, record, or injury status that did not come from a tool result in this conversation. If you need a number, call a tool. If tools can't answer, say so.
2. Use tools for anything about rosters, players, trades, the waiver wire, news, or the lineup. Team lookups work by owner first name (e.g. "Kaden").
3. Explain in plain English. Assume the user doesn't know football jargon: explain terms like FLEX, bye week, waiver claim in a few words the first time. Describe "value" as "how many more points than a free replacement player over the rest of the season".
4. For trade requests: call find_trades (or evaluate_trade for a specific deal) and present the best 1-3 options. For each, say who is given/received, the value split, how each team's lineup changes, and why the other manager might accept. If the user names a split like 60/40, use it as target_split (60 = in their favor). Mention if a trade needs a drop or a waiver pickup. If none are good, say so honestly.
5. You are READ-ONLY. You cannot make moves. End every recommendation with a line starting "Do this in the ESPN app:" saying exactly what to tap/propose.
6. Call log_recommendation once for each concrete recommendation you make (trade, lineup change, waiver move).
7. EDGES: projections you see may be "adjusted" = ESPN's number plus edge-engine adjustments (injury cascades, game environment, weather, opposing-defense/OL injuries, opportunity-vs-production tags). When a recommendation depends on an adjustment, call get_edges and CITE it: give ESPN's number, the adjusted number, which adjustment drove it, its size, its source and confidence. If a tool says there is no adjustment or data was missing, say so; never claim an edge a tool did not return. News statuses marked AI-extracted come from article text and may be wrong; cite the source link when you use one. buy-low/sell-high tags were validated in a backtest; "role growing" was not.
8. Be concise. Lead with the answer, then the reasoning. Flag uncertainty (questionable injuries, trending news)."""


@dataclass
class TurnResult:
    text: str
    history: list[dict]
    tool_trace: list[dict] = field(default_factory=list)
    session_id: Optional[str] = None      # subscription backend: resume token for the conversation


def _block_to_dict(b) -> dict:
    t = getattr(b, "type", None)
    if t == "text":
        return {"type": "text", "text": b.text}
    if t == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    raise ValueError(f"unexpected block type {t}")


def run_turn(client, model_name: str, tools: AgentTools, history: list[dict], user_text: str,
             max_tokens: int = 2048) -> TurnResult:
    """One user message -> (possibly many tool rounds) -> final text. `history` is plain JSON-able dicts."""
    messages = list(history) + [{"role": "user", "content": user_text}]
    system = [{"type": "text", "text": system_prompt(tools.snap), "cache_control": {"type": "ephemeral"}}]
    trace: list[dict] = []
    tools.logged_explicitly = False

    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(model=model_name, max_tokens=max_tokens, system=system, tools=TOOLS, messages=messages)
        blocks = [_block_to_dict(b) for b in resp.content if getattr(b, "type", None) in ("text", "tool_use")]
        messages.append({"role": "assistant", "content": blocks})
        calls = [b for b in blocks if b["type"] == "tool_use"]
        if resp.stop_reason != "tool_use" or not calls:
            break
        results = []
        for c in calls:
            out, is_err = tools.call(c["name"], c["input"])
            trace.append({"tool": c["name"], "input": c["input"], "error": is_err, "result": out})
            results.append({"type": "tool_result", "tool_use_id": c["id"], "content": json.dumps(out)[:30000], "is_error": is_err})
        messages.append({"role": "user", "content": results})
    else:
        messages.append({"role": "assistant", "content": [{"type": "text", "text": "(I hit my tool-call limit; please ask again more narrowly.)"}]})

    text = "\n".join(b["text"] for b in messages[-1]["content"] if b["type"] == "text").strip()
    used = [t["tool"] for t in trace if t["tool"] in RECOMMENDATION_TOOLS and not t["error"]]
    if used and not tools.logged_explicitly:      # safety net so every recommendation is logged
        db.log_recommendation(RECOMMENDATION_TOOLS[used[0]], (text or user_text)[:500],
                              {"question": user_text, "tools": [t["tool"] for t in trace]}, tools.snap.week, "agent", tools.db_path)
    return TurnResult(text, messages, trace)


# ---------------------------------------------------------------------------
# Subscription backend: Claude Agent SDK (uses your local Claude Code login, no API key)
# ---------------------------------------------------------------------------
SDK_SERVER = "fantasy"


def subscription_available() -> tuple[bool, str]:
    """(ok, reason). True when the Agent SDK is installed and the `claude` CLI is logged in."""
    import shutil
    import subprocess
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False, "Run: pip install claude-agent-sdk"
    cli = shutil.which("claude") or shutil.which("claude", path=f"{__import__('os').path.expanduser('~')}/.local/bin")
    if not cli:
        return False, "Claude Code isn't installed (the `claude` command wasn't found)."
    try:
        out = subprocess.run([cli, "auth", "status"], capture_output=True, text=True, timeout=20).stdout
        if json.loads(out).get("loggedIn"):
            return True, ""
    except Exception:
        pass
    return False, "Claude Code isn't logged in. Run `claude` in a terminal and sign in with your Claude account."


async def _run_turn_sdk(model_name: str, tools: AgentTools, session_id: Optional[str], user_text: str) -> TurnResult:
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, create_sdk_mcp_server,
                                  query, tool)
    trace: list[dict] = []
    tools.logged_explicitly = False

    def make(spec: dict):
        @tool(spec["name"], spec["description"], spec["input_schema"])
        async def handler(args: dict) -> dict:
            out, is_err = tools.call(spec["name"], args)
            trace.append({"tool": spec["name"], "input": args, "error": is_err, "result": out})
            return {"content": [{"type": "text", "text": json.dumps(out)[:30000]}], "is_error": is_err}
        return handler

    server = create_sdk_mcp_server(SDK_SERVER, "1.0.0", tools=[make(t) for t in TOOLS])
    options = ClaudeAgentOptions(
        system_prompt=system_prompt(tools.snap),
        mcp_servers={SDK_SERVER: server},
        tools=[],                                                    # no built-in file/shell/web tools
        allowed_tools=[f"mcp__{SDK_SERVER}__{t['name']}" for t in TOOLS],
        setting_sources=[],                                          # ignore any CLAUDE.md / hooks on this machine
        max_turns=MAX_TOOL_ROUNDS + 2,
        model=model_name or None,
        resume=session_id,
        env={"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""},   # force the claude.ai subscription login
    )
    texts: list[str] = []
    new_session = session_id
    async for msg in query(prompt=user_text, options=options):
        if isinstance(msg, AssistantMessage):
            turn_text = [b.text for b in msg.content if isinstance(b, TextBlock)]
            has_tool = any(getattr(b, "type", "") == "tool_use" or b.__class__.__name__ == "ToolUseBlock" for b in msg.content)
            if turn_text and not has_tool:
                texts = turn_text                         # keep only the last tool-free assistant message
        elif isinstance(msg, ResultMessage):
            new_session = msg.session_id or new_session
            if msg.is_error:
                raise RuntimeError(msg.result or "Claude returned an error.")
            if not texts and msg.result:
                texts = [msg.result]
    text = "\n".join(texts).strip()
    used = [t["tool"] for t in trace if t["tool"] in RECOMMENDATION_TOOLS and not t["error"]]
    if used and not tools.logged_explicitly:
        db.log_recommendation(RECOMMENDATION_TOOLS[used[0]], (text or user_text)[:500],
                              {"question": user_text, "tools": [t["tool"] for t in trace]}, tools.snap.week, "agent", tools.db_path)
    return TurnResult(text, [], trace, new_session)


def run_turn_subscription(model_name: str, tools: AgentTools, session_id: Optional[str], user_text: str) -> TurnResult:
    import asyncio
    return asyncio.run(_run_turn_sdk(model_name, tools, session_id, user_text))
