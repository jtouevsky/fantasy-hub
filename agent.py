"""Claude-powered chat agent with tool use. Every number it states must come from a tool result.

Read-only: no tool can change anything on ESPN; every recommendation ends with an ESPN-app action for you.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import db
import news as news_mod
import trades as trades_mod
import waivers as waivers_mod
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
                 db_path: Optional[str] = None):
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
7. Be concise. Lead with the answer, then the reasoning. Flag uncertainty (questionable injuries, trending news)."""


@dataclass
class TurnResult:
    text: str
    history: list[dict]
    tool_trace: list[dict] = field(default_factory=list)


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
