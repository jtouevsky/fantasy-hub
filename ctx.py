"""Shared per-session context for all views: data, model, branding, and cross-page actions."""
from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import agent
import db
import demo_data
import hub as hub_mod
import optimizer
import sleeper
import strategy as strategy_mod
from config import Config, load_config
from league_client import LeagueClient, get_activity, get_free_agents, get_market, get_player_history, get_snapshot
from models import LeagueSnapshot, PlayerInfo, TeamInfo
from optimizer import LineupPlan, plan_lineup
from edge import apply as edge_apply, live as edge_live, news_ai
from edge.engine import EngineResult
from valuation import ValueModel

FA_POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]


_CLIENT: Optional[LeagueClient] = None
_LOCK = threading.RLock()
# process-wide caches (this is a single-user local app): everything expensive is computed once per data refresh, never per navigation
STORE: dict = {"demo": False, "nonce": 0, "ctx_data": None, "edge": None, "model": None, "hub": None, "sub_ok": None, "ctx": None}


def _client() -> LeagueClient:
    global _CLIENT
    with _LOCK:
        if _CLIENT is None:
            _CLIENT = LeagueClient(load_config())
        return _CLIENT


def reset_client() -> None:
    global _CLIENT
    with _LOCK:
        _CLIENT = None


def using_demo() -> bool:
    return bool(STORE["demo"]) or os.getenv("DEMO_MODE") == "1"


def set_demo(on: bool) -> None:
    with _LOCK:
        STORE["demo"] = bool(on)
        for k in ("ctx_data", "edge", "model", "hub", "ctx"):
            STORE[k] = None


@dataclass
class Ctx:
    cfg: Config
    demo: bool
    snap: LeagueSnapshot
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
    _memo: dict = field(default_factory=dict, repr=False)

    def memo(self, key, fn):
        """Compute-once cache scoped to this context (a new context after Refresh/strategy change empties it), so heavy results are never recomputed on navigation."""
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    # ---- convenience ----
    @property
    def me(self) -> TeamInfo:
        return self.snap.my_team

    @property
    def opp(self) -> Optional[TeamInfo]:
        m = self.snap.matchup_for(self.me.team_id)
        return self.snap.team(m.opponent_of(self.me.team_id)) if m else None

    def plan(self) -> LineupPlan:
        if getattr(self, "_plan", None) is None:
            self._plan = plan_lineup(self.me.roster, self.snap.starter_slots)
        return self._plan

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


def load_ctx(force: bool = False) -> Ctx:
    """Uncached build (tests, refresh). Navigation uses get_ctx(), which returns the process-wide cached one."""
    with _LOCK:
        return _load_ctx(force)


def get_ctx(force: bool = False) -> Ctx:
    """The shared context. Rebuilt only on Refresh, when the data TTL expires, or when something (strategy, demo toggle, news scan) invalidates it,
    so switching tabs never recomputes the value model, edge adjustments or hub."""
    with _LOCK:
        c = STORE["ctx"]
        ttl = load_config().cache_ttl
        if force or c is None or (time.time() - STORE.get("ctx_at", 0)) > ttl:
            c = STORE["ctx"] = _load_ctx(force)
            STORE["ctx_at"] = time.time()
            STORE["version"] = STORE.get("version", 0) + 1
        return c


def invalidate() -> None:
    """Drop the cached context (next get_ctx rebuilds from the cached ESPN snapshot; the network is only hit if that cache expired)."""
    with _LOCK:
        STORE["ctx"] = None
        STORE["hub"] = None


def _load_ctx(force: bool = False) -> Ctx:
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
    cached = STORE["ctx_data"]
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
        STORE["ctx_data"] = {"key": key, "fas": fas, "index": index, "trending": trending}

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
        ek = (snap.fetched_at, edge_live.events_signature(cfg.db_path), STORE["nonce"])
        ce = STORE["edge"]
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
            STORE["edge"] = {"key": ek, "res": edge}
        if edge:
            edge_apply.apply_result(all_players, edge)
            warnings += [w for w in edge.warnings[:3]]
            try:                                    # stability-weighted value: TDs regressed to expected, volume kept; floor/median/ceiling ratios
                from edge import scoring as edge_scoring, stable as edge_stable
                h = edge_live.get_hist(snap.year, cfg.db_path)
                edge_stable.apply_to_players(all_players, edge_stable.live_stable(h, all_players, edge.gsis_of, snap.year, snap.week, edge_scoring.weights(path=cfg.db_path)))
            except Exception as e:
                warnings.append(f"Stability model unavailable ({type(e).__name__}); values use raw points per game.")
            try:                                    # score earlier recommendations whose weeks have completed
                import tracking
                tracking.score(cfg.db_path, edge_live.get_hist(snap.year, cfg.db_path).weekly, snap.year, snap.week)
            except Exception:
                pass
        scan_status = _maybe_scan(snap, fas, edge, cfg, force)

    optimizer.set_risk_mode(strategy_mod.load(cfg.db_path).risk_mode)
    mkey = (key, (STORE["edge"] or {}).get("key") if not demo else None)
    cm = STORE["model"]
    if cm and cm["key"] == mkey and not force:
        model = cm["model"]
    else:
        model = ValueModel(snap, fas)
        STORE["model"] = {"key": mkey, "model": model}

    hub = _build_hub(snap, model, fas, edge, cfg, demo, mkey, warnings, force, events)

    ctx = Ctx(cfg, demo, snap, model, fas, index, trending, warnings, age, edge, events, scan_status, load_watchlist(cfg.db_path), hub=hub)
    return ctx


def _build_hub(snap, model, fas, edge, cfg, demo, mkey, warnings, force, events=()) -> hub_mod.Hub:
    """The v2 engines (strategy, season model, market, trade world, move engine), rebuilt when data or strategy changes."""
    strat = strategy_mod.load(cfg.db_path)
    from dataclasses import asdict
    hk = (mkey, json.dumps(asdict(strat), sort_keys=True, default=str))
    ch = STORE["hub"]
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
    hub = hub_mod.build(snap, model, fas, cfg.db_path, signals, activity, dst, dst_next, strat, hub_mod.news_reasons(events, edge, [p for t in snap.teams for p in t.roster] + list(fas)))
    STORE["hub"] = {"key": hk, "hub": hub}
    return hub


def _sub_ok() -> bool:
    if STORE["sub_ok"] is None:
        import agent
        STORE["sub_ok"] = agent.subscription_available()[0]
    return STORE["sub_ok"]


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
