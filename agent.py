"""Claude-powered chat agent with tool use. Every number it states must come from a tool result.

Read-only: no tool can change anything on ESPN; every recommendation ends with an ESPN-app action for you.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import acceptance as acceptance_mod
import db
import hub as hub_mod
import moves as moves_mod
import news as news_mod
import strategy as strategy_mod
import trading
import assets
from ui import EDGE_LABEL
from models import LeagueSnapshot, PlayerInfo
from optimizer import plan_lineup
from sleeper import SleeperIndex
from valuation import ValueModel

MAX_TOOL_ROUNDS = 10
RECOMMENDATION_TOOLS = {"find_trades": "trade", "evaluate_trade": "trade", "optimize_lineup": "lineup",
                        "find_moves": "waiver", "evaluate_move": "waiver"}


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
                 db_path: Optional[str] = None, edge=None, events: Optional[list] = None, hub: Optional[hub_mod.Hub] = None):
        self.edge, self.events = edge, events or []
        self.snap, self.model = snap, model
        self.fetch_free_agents, self.fetch_news = fetch_free_agents, fetch_news
        self.index, self.trending, self.db_path = sleeper_index, trending or {}, db_path
        self.logged_explicitly = False
        self._hub = hub

    @property
    def hub(self) -> hub_mod.Hub:
        """The SAME engines the UI uses (built lazily from the free-agent fetcher when no hub was passed, e.g. in tests/demo)."""
        if self._hub is None:
            fas = self._fas() + [p for pos in ("K", "D/ST") for p in self.fetch_free_agents(pos, 30)]
            self._hub = hub_mod.build(self.snap, self.model, fas, self.db_path)
        return self._hub

    # ---- helpers ---------------------------------------------------------
    def _player_row(self, p: PlayerInfo) -> dict:
        """Facts only. No placeholder 'value' numbers (a below-replacement player is never reported as 0.0) and no bye info unless it is this week's."""
        s = self.hub.season
        row = {
            "name": p.name, "position": p.position, "nfl_team": p.pro_team, "lineup_slot": p.lineup_slot,
            "injury_status": p.injury_status, "projected_points_this_week": _r(p.week_proj), "points_per_game_so_far": _r(p.actual_ppg),
            "expected_points_rest_of_season": _r(s.raw_ros(p), 0),
        }
        if p.on_bye:
            row["on_bye_this_week"] = True
        if p.injury_status in ("INJURY_RESERVE", "OUT", "SUSPENSION", "DOUBTFUL", "QUESTIONABLE"):
            row["injury_outlook"] = s.timeline(p).note
        if p.has_edge or p.tags:
            row.update({"espn_projection": _r(p.espn_week_proj), "edge_adjustment": _r(p.edge_total), "tags": [t[0] for t in p.tags]})
        return row

    def _team_row(self, t) -> dict:
        s = self.hub.season
        return {"team_name": t.name, "owner": t.owner_label, "record": t.record, "standing": t.standing,
                "points_for": _r(t.points_for), "players": [self._player_row(p) for p in sorted(t.roster, key=lambda p: -s.rank_key(p))]}

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
        s = self.hub.season
        fas.sort(key=lambda p: -s.rank_key(p))
        note = "Raw facts for browsing only. To recommend an add, call find_moves or evaluate_move (they apply the roster rules); never build a move from this list."
        out = []
        for p in fas[:max(1, min(limit, 30))]:
            sid = self.index.find(p) if self.index else None
            out.append({**self._player_row(p), "percent_owned": p.percent_owned, "sleeper_trending_adds_24h": self.trending.get(sid) if sid else None})
        return {"free_agents": out, "note": note}

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
        ev = trading.evaluate(self.hub.world, other, give_p, get_p)
        ev.ladder = trading.build_ladder(self.hub.world, ev, trading.Constraints(), trading._my_pool(self.hub.world, trading.Constraints()), [])
        return trading.describe(self.hub.world, ev)

    def find_trades(self, request: str = "", target_team: Optional[str] = None, offering: Optional[list[str]] = None, get: Optional[list[str]] = None,
                    target_split: Optional[float] = None, want_positions: Optional[list[str]] = None, exclude_give_positions: Optional[list[str]] = None,
                    need_position: Optional[str] = None, allow_loss: Optional[bool] = None, max_results: int = 5) -> dict:
        """Whole-league scan unless target_team is given. A free-text `request` is parsed into explicit constraints; explicit arguments override it. The parsed constraints are echoed back."""
        w = self.hub.world
        c = trading.parse_request(request, w) if request else trading.Constraints()
        if target_team:
            c.partner = self.snap.find_team(target_team).team_id
        if offering:
            c.offering = [p.player_id for p in self._resolve_mine(offering)]
        if get:
            c.get_ids = [self.snap.find_player(n).player_id for n in get]
        if target_split is not None:
            c.target_split = float(target_split)
        if want_positions:
            c.want_positions = {x.upper() for x in want_positions}
        if exclude_give_positions:
            c.exclude_give_positions = {x.upper() for x in exclude_give_positions}
        if need_position:
            c.need_position = need_position.upper()
        if allow_loss is not None:
            c.allow_loss = allow_loss
        c.max_results = max(1, min(max_results, 8))
        found = trading.search(w, c)
        return {"parsed_constraints": c.summary(), "parse_notes": c.notes, "n_found": len(found), "trades": [trading.describe(w, e) for e in found],
                "note": "Two separate questions: should_i_offer uses MY value (my lineup); would_they_accept uses THEIR perception (market value, need, situation, history). Never merge them. "
                        "Present trades in the order given; quote labels, never invent percentages."}

    def draft_trade_pitch(self, give: list[str], get: list[str], team_name_or_owner: str) -> dict:
        other = self.snap.find_team(team_name_or_owner)
        ev = trading.evaluate(self.hub.world, other, self._resolve_mine(give), [self.snap.find_player(n, other) for n in get])
        return {"message": trading.pitch(self.hub.world, ev), "note": "Draft only; the user sends it themselves. Nothing is sent automatically."}

    def log_negotiation(self, manager: str, offer: dict, response: str, note: str = "") -> dict:
        """Record how a manager actually responded ('accepted' | 'rejected' | 'countered' | 'no response'). offer = {give: [my player names], get: [their player names]}."""
        other = self.snap.find_team(manager)
        give = self._resolve_mine(offer.get("give", []))
        get = [self.snap.find_player(n, other) for n in offer.get("get", [])]
        nid = acceptance_mod.log_negotiation(self.db_path, other.team_id, other.owner_label or other.name, give, get, response, note)
        return {"logged": True, "id": nid, "note": "Future 'would they accept' estimates for this manager now use this result."}

    def get_manager_profile(self, manager: str) -> dict:
        other = self.snap.find_team(manager)
        prof = acceptance_mod.manager_profile(self.db_path, other, self.hub.world.stats, self.hub.market)
        return {"team": other.name, "owner": other.owner_label, **prof}

    def get_strategy(self) -> dict:
        from dataclasses import asdict
        s = self.hub.strategy
        return {**asdict(s), "streaming_positions": sorted(s.streaming), "roster_caps": s.caps(self.snap.starter_slots)}

    def find_moves(self, max_moves: int = 3) -> dict:
        """THE source of add/drop and streaming recommendations (also what the Waivers page shows). 'No move needed' is a valid result."""
        ms = self.hub.moves.find_moves(max(1, min(int(max_moves), 3)))
        return {**ms.to_dict(), "note": "Recommend ONLY what is listed here, in this order. Streaming picks are decided on THIS week's matchup; if no_move_needed is true, say so plainly."}

    def evaluate_move(self, add: str, drop: Optional[str] = None) -> dict:
        """Check one specific add/drop against the roster rules and the gain thresholds."""
        eng = self.hub.moves
        pool = {p.name.lower(): p for p in self._fas() + [x for pos in ("K", "D/ST") for x in self.fetch_free_agents(pos, 30)]}
        a = pool.get(add.lower()) or next((p for p in pool.values() if add.lower() in p.name.lower()), None)
        if a is None:
            raise LookupError(f"Couldn't find free agent '{add}'.")
        d = self.snap.find_player(drop, self.snap.my_team) if drop else None
        m = eng.evaluate_move(a, d)
        return {**m.to_dict(), "allowed": m.ok, "blocked_because": m.blocked}

    def optimize_lineup(self) -> dict:
        plan = plan_lineup(self.snap.my_team.roster, self.snap.starter_slots)
        row = lambda rows: [{"slot": s, "player": p.name if p else None, "projected": _r(p.week_proj) if p else 0,
                             "injury_status": p.injury_status if p else None} for s, p in rows]
        return {"current_lineup": row(plan.current), "optimal_lineup": row(plan.optimal),
                "current_projected_total": plan.current_total, "optimal_projected_total": plan.optimal_total,
                "gain": _r(plan.gain), "swaps": [{"gain": s.gain, "action": s.action(), "reason": s.reason} for s in plan.swaps],
                "warnings": plan.warnings}

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
                "context_not_in_projection": [{"kind": c["kind"], "text": c["text"], "estimated_points": c["pts"], "confidence": c.get("confidence", "low")} for c in p.context],
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
                "note": "weekly_pts = estimated change in that player's fantasy points if usage shifts as history suggests. IMPORTANT: this is context, not a validated adjustment - "
                        "the backtest found the share-transfer estimate does not improve weekly accuracy over recent form, so it is NOT included in projections. Say so when you use it."}

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
                                      "why": why, "expected_points_rest_of_season": _r(self.hub.season.raw_ros(p), 0)})
        for k in out:
            out[k] = sorted(out[k], key=lambda r: -r["expected_points_rest_of_season"])[:10]
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

    def strategy_text(self) -> str:
        return strategy_mod.prompt_block(self.hub.strategy, self.snap.starter_slots, self.snap.week)

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
    {"name": "evaluate_trade", "description": "Evaluate one specific trade. Returns two SEPARATE answers: should_i_offer (my value and lineup change, week by week) and would_they_accept (market value, need, situation, history; a label plus reasons), plus risk and an offer ladder (Open/Fair/Walk away). 'give' = my players, 'get' = their players.",
     "input_schema": {"type": "object", "properties": {"give": _STRS, "get": _STRS, "team_name_or_owner": _STR}, "required": ["give", "get"]}},
    {"name": "find_trades", "description": "Search the WHOLE league (or one team) for trades, cheapest winning offer first (1-for-1 before 2-for-1, no unneeded sweeteners). Pass the user's plain-English words in `request` (e.g. 'a WR for the playoffs without giving up an RB, 60/40') and/or explicit arguments; the parsed constraints are returned so they can be shown and corrected.",
     "input_schema": {"type": "object", "properties": {"request": _STR, "target_team": _STR, "offering": _STRS, "get": _STRS, "target_split": {"type": "number"},
                                                        "want_positions": _STRS, "exclude_give_positions": _STRS, "need_position": _STR, "allow_loss": {"type": "boolean"},
                                                        "max_results": {"type": "integer"}}}},
    {"name": "draft_trade_pitch", "description": "Draft a short, casual message to the other manager highlighting what THEY gain. Never sent automatically; the user sends it.",
     "input_schema": {"type": "object", "properties": {"give": _STRS, "get": _STRS, "team_name_or_owner": _STR}, "required": ["give", "get", "team_name_or_owner"]}},
    {"name": "log_negotiation", "description": "Record how a manager really responded to an offer so future 'would they accept' estimates improve. response: accepted | rejected | countered | no response. offer = {give: [my player names], get: [their player names]}.",
     "input_schema": {"type": "object", "properties": {"manager": _STR, "offer": {"type": "object", "properties": {"give": _STRS, "get": _STRS}}, "response": _STR, "note": _STR}, "required": ["manager", "offer", "response"]}},
    {"name": "get_manager_profile", "description": "A manager's trade tendencies: logged negotiations, league activity (trades/adds), and what they have said yes/no to.",
     "input_schema": {"type": "object", "properties": {"manager": _STR}, "required": ["manager"]}},
    {"name": "get_strategy", "description": "My strategy settings: streaming positions, roster caps, thresholds, recently-added protection.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "optimize_lineup", "description": "Best starting lineup for this week vs my current lineup, with each swap's projected gain.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "find_moves", "description": "THE ONLY source of add/drop and streaming recommendations (the Waivers page uses the same engine). Applies my strategy, roster caps, recently-added protection and projection sanity checks. Returns at most 3 ranked moves with this-week gain, rest-of-season gain, a one-line reason and confidence, plus streaming picks. no_move_needed=true is a valid answer.",
     "input_schema": {"type": "object", "properties": {"max_moves": {"type": "integer"}}}},
    {"name": "evaluate_move", "description": "Check one specific add/drop against the roster rules and gain thresholds; returns allowed true/false with the reasons it is blocked.",
     "input_schema": {"type": "object", "properties": {"add": _STR, "drop": _STR}, "required": ["add"]}},
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
def system_prompt(snap: LeagueSnapshot, strategy_text: str = "") -> str:
    me = snap.my_team
    return f"""You are a fantasy football assistant for one person who plays in an ESPN league. They want you to do the thinking for them.

League: {snap.league_name}. It is week {snap.week} of the {snap.year} season. Their team is "{me.name}" (owner {me.owner_label}), record {me.record}.
Starting slots: {', '.join(f'{n}x {s}' for s, n in snap.starter_slots.items())}; {snap.bench_slots} bench spots. Scoring: {snap.scoring_notes}.
{strategy_text}

Rules you must follow:
1. NEVER state a stat, projection, value, record, or injury status that did not come from a tool result in this conversation. Cite the tool output you rely on.
2. ADD/DROP and STREAMING: call find_moves (or evaluate_move for a specific idea) and recommend ONLY what it returns, in its order. You do no valuation of your own: never assemble a move from get_free_agents, never quote a "value" of 0.0, never mention bye weeks unless it is this week's, never suggest a position the strategy caps or a player added within the protection window. If find_moves says no_move_needed, answer "No move needed" with its one-line reason; that is a good answer.
3. Format for moves: at most 3, ranked. Each: Add X / Drop Y; this-week gain; rest-of-season gain; ONE line of reason; confidence (high/medium/low). Mark speculative ones as such. For streaming, say "keep your current D/ST" when the tool says swap=false.
4. TRADES: call find_trades (whole league by default; pass the user's words as `request`) or evaluate_trade. Always answer TWO separate questions and never blend them: (a) should the user offer it (their value and lineup, week by week) and (b) would the other manager accept (market value, need, situation, history; use the label likely / coin flip / unlikely and the listed reasons; never invent percentages). Include the offer ladder (Open/Fair/Walk away), the risk, and say which constraints you parsed so they can correct them. If none are good, say so.
5. After any negotiation outcome the user reports, call log_negotiation. Use get_manager_profile before judging how a specific manager will respond.
6. You are READ-ONLY. You cannot make moves or send messages (draft_trade_pitch only drafts). End every recommendation with a line starting "Do this in the ESPN app:".
7. Call log_recommendation once for each concrete recommendation. Write your COMPLETE answer as plain text in your final message; never leave the explanation only in a message that also calls a tool.
8. EDGES: projections may be "adjusted" (ESPN's number plus edge-engine adjustments). When a recommendation depends on one, call get_edges and CITE it (ESPN number, adjusted number, driver, size, source, confidence). If a tool says there is no adjustment or data was missing, say so; never claim an edge a tool did not return. News statuses marked AI-extracted come from article text and may be wrong; cite the source link. Injury-cascade estimates are context only; buy-low/sell-high tags were backtested; "role growing" was not.
9. Be concise and plain. Explanation level is set in the strategy (Short = no definitions; Beginner = define terms briefly). Lead with the answer; flag uncertainty."""


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
    system = [{"type": "text", "text": system_prompt(tools.snap, tools.strategy_text()), "cache_control": {"type": "ephemeral"}}]
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

    pieces = []
    for m in messages[len(history) + 1:]:           # every assistant message of this turn that wrote text beside only log_recommendation calls (or no tools)
        if m["role"] != "assistant":
            continue
        calls = [b["name"] for b in m["content"] if b["type"] == "tool_use"]
        if not calls or all(n == "log_recommendation" for n in calls):
            pieces.append("\n".join(b["text"] for b in m["content"] if b["type"] == "text").strip())
    text = _final_answer(pieces)
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


def _final_answer(parts: list[str]) -> str:
    """Join the answer pieces; drop a trailing 'I've logged it' confirmation when a real answer came before it."""
    parts = [p for p in parts if p]
    if len(parts) >= 2 and len(parts[-1]) < 160 and re.search(r"\blogged\b", parts[-1], re.I):
        parts = parts[:-1]
    return "\n\n".join(parts).strip()


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
        system_prompt=system_prompt(tools.snap, tools.strategy_text()),
        mcp_servers={SDK_SERVER: server},
        tools=[],                                                    # no built-in file/shell/web tools
        allowed_tools=[f"mcp__{SDK_SERVER}__{t['name']}" for t in TOOLS],
        setting_sources=[],                                          # ignore any CLAUDE.md / hooks on this machine
        max_turns=MAX_TOOL_ROUNDS + 2,
        model=model_name or None,
        resume=session_id,
        env={"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""},   # force the claude.ai subscription login
    )
    answer_parts: list[str] = []
    new_session = session_id
    async for msg in query(prompt=user_text, options=options):
        if isinstance(msg, AssistantMessage):
            turn_text = "\n".join(b.text for b in msg.content if isinstance(b, TextBlock)).strip()
            tool_names = [getattr(b, "name", "") for b in msg.content if b.__class__.__name__ == "ToolUseBlock"]
            only_logging = bool(tool_names) and all(n.endswith("log_recommendation") for n in tool_names)
            if turn_text and (not tool_names or only_logging):
                answer_parts.append(turn_text)       # the answer may sit in the same message that logs it; keep it
        elif isinstance(msg, ResultMessage):
            new_session = msg.session_id or new_session
            if msg.is_error:
                raise RuntimeError(msg.result or "Claude returned an error.")
            if not answer_parts and msg.result:
                answer_parts = [msg.result]
    texts = _final_answer(answer_parts)
    text = texts
    used = [t["tool"] for t in trace if t["tool"] in RECOMMENDATION_TOOLS and not t["error"]]
    if used and not tools.logged_explicitly:
        db.log_recommendation(RECOMMENDATION_TOOLS[used[0]], (text or user_text)[:500],
                              {"question": user_text, "tools": [t["tool"] for t in trace]}, tools.snap.week, "agent", tools.db_path)
    return TurnResult(text, [], trace, new_session)


def run_turn_subscription(model_name: str, tools: AgentTools, session_id: Optional[str], user_text: str) -> TurnResult:
    import asyncio
    return asyncio.run(_run_turn_sdk(model_name, tools, session_id, user_text))
