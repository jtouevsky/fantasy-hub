"""Shared per-session context for all views: data, model, branding, and cross-page actions."""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import streamlit as st

import agent
import db
import demo_data
import hub as hub_mod
import sleeper
import strategy as strategy_mod
from config import Config, load_config
from league_client import LeagueClient, get_activity, get_free_agents, get_market, get_player_history, get_snapshot
from models import LeagueSnapshot, PlayerInfo, TeamInfo
from optimizer import LineupPlan, plan_lineup
from ui import Brand
from edge import apply as edge_apply, live as edge_live, news_ai
from edge.engine import EngineResult
from valuation import ValueModel

FA_POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]


@st.cache_resource
def _client() -> LeagueClient:
    return LeagueClient(load_config())


def using_demo() -> bool:
    return bool(st.session_state.get("demo")) or os.getenv("DEMO_MODE") == "1"


@dataclass
class Ctx:
    cfg: Config
    demo: bool
    snap: LeagueSnapshot
    brand: Brand
    model: ValueModel
    fas: list[PlayerInfo]
    index: Optional[sleeper.SleeperIndex]
    trending: dict
    warnings: list[str] = field(default_factory=list)
    age: Optional[float] = None            # seconds since the snapshot was fetched
    edge: Optional[EngineResult] = None    # edge-engine output for this week (None in demo mode / if it failed)
    events: list = field(default_factory=list)   # AI-parsed news events
    scan_status: str = ""
    watchlist: set = field(default_factory=set)
    hub: Optional[hub_mod.Hub] = None      # v2 engines: strategy, season model, market, trade world, move engine

    # ---- convenience ----
    @property
    def me(self) -> TeamInfo:
        return self.snap.my_team

    @property
    def opp(self) -> Optional[TeamInfo]:
        m = self.snap.matchup_for(self.me.team_id)
        return self.snap.team(m.opponent_of(self.me.team_id)) if m else None

    def plan(self) -> LineupPlan:
        key = ("plan", self.snap.fetched_at)
        if st.session_state.get("_plan_key") != key:
            st.session_state["_plan"], st.session_state["_plan_key"] = plan_lineup(self.me.roster, self.snap.starter_slots), key
        return st.session_state["_plan"]

    def everyone(self) -> dict[int, PlayerInfo]:
        d = {p.player_id: p for p in self.fas}
        d.update({p.player_id: p for t in self.snap.teams for p in t.roster})
        return d

    def owner_of(self, p: PlayerInfo) -> Optional[TeamInfo]:
        return self.snap.team(p.owner_team_id) if p.owner_team_id else None

    # ---- data sources that may be missing in demo ----
    def news_fetch(self):
        return None if self.demo else (lambda pid, n: _client().fetch_player_news(pid, n))

    def free_agents(self, position=None, size=30):
        if self.demo:
            return [p for p in demo_data.build_demo_free_agents() if position in (None, p.position)]
        return get_free_agents(_client(), position, size)

    def history(self, p: PlayerInfo) -> list[dict]:
        if self.demo:                                   # labeled demo data only
            rnd = random.Random(p.player_id)
            base = p.season_proj_ppg or 8
            return [{"season": s, "week": w, "points": round(max(0, rnd.gauss(base, base * .35)), 1), "source": "demo"}
                    for s, ws in ((2025, range(5, 19)), (2026, range(1, self.snap.week))) for w in ws]
        return get_player_history(_client(), p.player_id)

    def agent_tools(self) -> agent.AgentTools:
        return agent.AgentTools(self.snap, self.model, lambda pos, n: self.free_agents(pos, n), self.news_fetch(),
                                self.index, self.trending, self.cfg.db_path, self.edge, self.events, hub=self.hub)

    # ---- cross-page actions (callbacks) ----
    @staticmethod
    def open_player(pid: int) -> None:
        st.session_state["open_player"] = pid

    @staticmethod
    def ask_ai(prompt: str, title: str = "AI review") -> None:
        st.session_state["ai_sheet"] = {"prompt": prompt, "title": title}

    @staticmethod
    def goto(page: str, **state) -> None:
        st.session_state["page_req"] = page
        st.session_state.update(state)


def load_ctx(force: bool = False) -> Ctx:
    """Snapshot first (required). Everything else degrades to a warning instead of breaking the page."""
    cfg = load_config()
    demo = using_demo()
    warnings: list[str] = []
    if demo:
        snap = demo_data.build_demo_snapshot()
        age = 0.0
    else:
        client = _client()
        snap = get_snapshot(client, force=force)
        age = max(datetime.now().timestamp() - snap.fetched_at, 0)
        if client.last_warning:
            warnings.append(client.last_warning)

    key = (demo, snap.fetched_at)
    cached = st.session_state.get("_ctx_data")
    if cached and cached["key"] == key and not force:
        fas, index, trending = cached["fas"], cached["index"], cached["trending"]
    else:
        flexy = {"FLEX", "OP", "RB/WR", "WR/TE"} & set(snap.starter_slots)
        positions = [p for p in FA_POSITIONS if p in snap.starter_slots or (p in ("RB", "WR", "TE") and flexy) or (p == "QB" and "OP" in flexy)]
        fas: list[PlayerInfo] = []
        try:
            if demo:
                fas = demo_data.build_demo_free_agents()
            else:
                fas = [p for pos in positions for p in get_free_agents(_client(), pos, 30, force=force)]
        except Exception as e:
            warnings.append(f"Free-agent data unavailable ({type(e).__name__}). Waiver and value numbers may be less accurate.")
        index, trending = None, {}
        if not demo:
            try:
                index = sleeper.SleeperIndex(sleeper.load_players(cfg.db_path))
                trending = sleeper.trending_counts(index, "add", cfg.db_path)
            except Exception as e:
                warnings.append(f"Sleeper data unavailable ({type(e).__name__}); injury cross-checks and trending flags are off.")
        st.session_state["_ctx_data"] = {"key": key, "fas": fas, "index": index, "trending": trending}

    # ---- edge engine (real leagues only; demo players have no nflverse IDs) -------------------
    edge, events, scan_status = None, [], ""
    all_players = [p for t in snap.teams for p in t.roster] + list(fas)
    if not demo:
        for p in all_players:
            if not p.espn_week_proj:
                p.espn_week_proj = p.week_proj
        events = news_ai.load_events(db_path=cfg.db_path)
        try:
            from edge.engine import current_week_events
            events = current_week_events(edge_live.get_hist(snap.year, cfg.db_path), snap.year, snap.week, events)
        except Exception:
            pass
        ek = (snap.fetched_at, edge_live.events_signature(cfg.db_path), st.session_state.get("_edge_nonce", 0))
        ce = st.session_state.get("_edge")
        if ce and ce["key"] == ek and not force:
            edge = ce["res"]
        else:
            try:
                w = edge_live.ensure_scoring(_client(), cfg.db_path)
                if w:
                    warnings.append(w)
                if force:
                    edge_live.recheck_injuries(snap.year, cfg.db_path)
                edge = edge_live.run_live(snap, fas, index, cfg.db_path, snap.year, snap.week)
            except Exception as e:
                warnings.append(f"Edge engine unavailable ({type(e).__name__}: {str(e)[:80]}); showing ESPN projections as is.")
            st.session_state["_edge"] = {"key": ek, "res": edge}
        if edge:
            edge_apply.apply_result(all_players, edge)
            warnings += [w for w in edge.warnings[:3]]
        scan_status = _maybe_scan(snap, fas, edge, cfg, force)

    mkey = (key, st.session_state.get("_edge", {}).get("key") if not demo else None)
    cm = st.session_state.get("_model")
    if cm and cm["key"] == mkey and not force:
        model = cm["model"]
    else:
        model = ValueModel(snap, fas)
        st.session_state["_model"] = {"key": mkey, "model": model}

    hub = _build_hub(snap, model, fas, edge, cfg, demo, mkey, warnings, force)

    brand = Brand(cfg.db_path, {"espn_s2": cfg.espn_s2, "SWID": cfg.swid} if not demo and cfg.espn_s2 else None)
    ctx = Ctx(cfg, demo, snap, brand, model, fas, index, trending, warnings, age, edge, events, scan_status, load_watchlist(cfg.db_path), hub=hub)
    brand.watch = ctx.watchlist
    return ctx


def _build_hub(snap, model, fas, edge, cfg, demo, mkey, warnings, force) -> hub_mod.Hub:
    """The v2 engines (strategy, season model, market, trade world, move engine), rebuilt when data or strategy changes."""
    strat = strategy_mod.load(cfg.db_path)
    from dataclasses import asdict
    hk = (mkey, json.dumps(asdict(strat), sort_keys=True, default=str))
    ch = st.session_state.get("_hub")
    if ch and ch["key"] == hk and not force:
        return ch["hub"]
    signals, activity, dst, dst_next = {}, [], {}, {}
    if not demo:
        try:
            signals = get_market(_client(), force=force)
        except Exception as e:
            warnings.append(f"Market data unavailable ({type(e).__name__}); trade market values fall back to the model.")
        try:
            activity = get_activity(_client(), force=force)
        except Exception as e:
            warnings.append(f"League activity unavailable ({type(e).__name__}); manager history signals are off.")
        everyone = [p for t in snap.teams for p in t.roster] + list(fas)
        hub_mod.apply_return_games(everyone, edge)
        if strat.streaming:
            try:
                from edge import dst as dst_mod
                h = edge_live.get_hist(snap.year, cfg.db_path)
                seasons = [snap.year - 2, snap.year - 1, snap.year]
                dst = dst_mod.live_estimates(h, seasons, snap.year, snap.week)
                dst_next = dst_mod.live_estimates(h, seasons, snap.year, snap.week + 1)
            except Exception as e:
                warnings.append(f"D/ST matchup model unavailable ({type(e).__name__}); streaming uses ESPN's D/ST projection only.")
    hub = hub_mod.build(snap, model, fas, cfg.db_path, signals, activity, dst, dst_next, strat)
    st.session_state["_hub"] = {"key": hk, "hub": hub}
    return hub


def _sub_ok() -> bool:
    if "_sub_ok" not in st.session_state:
        import agent
        st.session_state["_sub_ok"] = agent.subscription_available()[0]
    return st.session_state["_sub_ok"]


def _maybe_scan(snap, fas, edge, cfg, force: bool) -> str:
    """Kick off (at most every 15 min) a background AI read of league news; never blocks the page."""
    sc = edge_live.SCANNER
    if sc.running:
        return f"AI news scan running ({sc.progress or 'working'})"
    if cfg.chat_backend == "api" or not _sub_ok():
        return "AI news scan needs the Claude subscription login (see Assistant)."
    try:
        starters = [p for p in snap.my_team.roster if p.lineup_slot not in ("BE", "IR")]
        opps = sorted({p.opponent for p in starters if p.opponent})
        hist = edge_live.get_hist(snap.year, cfg.db_path)
        players = edge_live.news_scan_players(snap, fas, edge, hist, opps)
        gsis_of = edge.gsis_of if edge else {}
        if edge_live.start_news_scan(players, lambda pid, n: _client().fetch_player_news(pid, n), gsis_of, cfg.db_path):
            return "AI news scan started"
    except Exception as e:
        return f"AI news scan unavailable ({type(e).__name__})"
    if sc.last_error:
        return f"Last AI news scan failed: {sc.last_error}"
    if sc.last_finished:
        return f"AI news scan finished {int((time.time() - sc.last_finished) / 60)} min ago"
    return ""


def load_watchlist(db_path) -> set:
    import json
    try:
        return set(json.loads(db.setting_get("watchlist", "[]", db_path)))
    except ValueError:
        return set()


def toggle_watch(pid: int, db_path) -> bool:
    """Add/remove a player from the watchlist. Returns True if he is now watched."""
    import json
    w = load_watchlist(db_path)
    now = pid not in w
    (w.add if now else w.discard)(pid)
    db.setting_set("watchlist", json.dumps(sorted(w)), db_path)
    return now
