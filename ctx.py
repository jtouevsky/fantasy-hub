"""Shared per-session context for all views: data, model, branding, and cross-page actions."""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import streamlit as st

import agent
import db
import demo_data
import sleeper
from config import Config, load_config
from league_client import LeagueClient, get_free_agents, get_player_history, get_snapshot
from models import LeagueSnapshot, PlayerInfo, TeamInfo
from optimizer import LineupPlan, plan_lineup
from ui import Brand
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
                                self.index, self.trending, self.cfg.db_path)

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
        fas, model, index, trending = cached["fas"], cached["model"], cached["index"], cached["trending"]
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
        model = ValueModel(snap, fas)
        index, trending = None, {}
        if not demo:
            try:
                index = sleeper.SleeperIndex(sleeper.load_players(cfg.db_path))
                trending = sleeper.trending_counts(index, "add", cfg.db_path)
            except Exception as e:
                warnings.append(f"Sleeper data unavailable ({type(e).__name__}); injury cross-checks and trending flags are off.")
        st.session_state["_ctx_data"] = {"key": key, "fas": fas, "model": model, "index": index, "trending": trending}

    brand = Brand(cfg.db_path)
    ctx = Ctx(cfg, demo, snap, brand, model, fas, index, trending, warnings, age)
    return ctx
