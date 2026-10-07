"""Live edge engine: turns this week's real data into stored, explainable adjustments on top of ESPN projections.

    adjusted_projection = espn_projection + sum(adjustments)          (total capped per player-week)

Pipeline: slate (roster + opponent + free agents, ESPN IDs) -> GSIS via the ID crosswalk -> merged injury state (nflverse
report, Sleeper, ESPN, parsed news; most severe wins, sources recorded) -> each validated module at its backtested strength
times a documented live haircut -> adjustments stored in SQLite. Missing data means NO adjustment, and the result says so.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

import numpy as np
import pandas as pd

import db
from edge import forecast as fx
from edge import ids, odds as odds_mod, store
from edge.features import game_context
from edge.history import Hist
from edge.modules.cascade import Cascade, compute_team, explain, p_for, practice_code, prep_for
from edge.modules.defense import Defense
from edge.modules.regression import Regression, signals_asof, tag_for
from edge.modules.vegas import Vegas
from edge.modules.weather import Weather
from edge.settings import EdgeSettings, load_params
from edge.types import Adjustment, AdjustedProjection

log = logging.getLogger("edge.engine")
MIN_ADJ = 0.15                      # ignore adjustments smaller than this (noise)
SEVERITY = {"Out": 3, "Doubtful": 2, "Questionable": 1}
SLEEPER_STATUS = {"Out": "Out", "IR": "Out", "PUP": "Out", "Sus": "Out", "NFI": "Out", "DNR": "Out", "COV": "Out", "Doubtful": "Doubtful", "Questionable": "Questionable"}
ESPN_STATUS = {"OUT": "Out", "INJURY_RESERVE": "Out", "SUSPENSION": "Out", "DOUBTFUL": "Doubtful", "QUESTIONABLE": "Questionable"}
NEWS_STATUS = {"out": "Out", "ir": "Out", "suspended": "Out", "doubtful": "Doubtful", "questionable": "Questionable"}
LONG_TERM_GAMES = 3                 # expected games missed at or above this => rest-of-season cascade
ROS_PERSIST = 0.8                   # share of a weekly cascade that persists per game for a long-term absence
SKILL = ("QB", "RB", "WR", "TE")
TAG_TEXT = {"buy low": "His opportunities (expected points) have outrun his production over the last 4 games; history says production catches up.",
            "sell high": "He has produced well above what his opportunities justify over the last 4 games; history says that fades.",
            "role growing": "His snap share has risen over the last 2 games (informational: backtest found this alone is not predictive)."}


@dataclass
class InjuryState:
    gsis: str
    name: str
    pos: str
    team: str
    status: str                     # Out / Doubtful / Questionable
    practice: str = ""              # dnp / limited / full
    sources: list[str] = field(default_factory=list)
    long_term: bool = False
    games_missed: Optional[int] = None


@dataclass
class GameEnv:
    team: str
    opp: str
    home: bool
    spread: Optional[float]         # positive = this team favored
    total: Optional[float]
    implied: Optional[float]
    opp_implied: Optional[float]
    lines_source: str               # 'odds-api' | 'nflverse schedule' | 'missing'
    kickoff: str = ""
    stadium: str = ""
    roof: str = ""
    wind_mph: Optional[float] = None
    temp_f: Optional[float] = None
    precip_prob: Optional[float] = None
    forecast_at: Optional[float] = None
    weather_note: str = ""


@dataclass
class EngineResult:
    season: int
    week: int
    generated_at: float
    projections: dict[int, AdjustedProjection] = field(default_factory=dict)      # by ESPN player id
    ros: dict[int, float] = field(default_factory=dict)                           # per-game rest-of-season points adjustment
    ros_notes: dict[int, list[str]] = field(default_factory=dict)
    tags: dict[int, list[tuple[str, str]]] = field(default_factory=dict)          # (tag, explanation)
    game_env: dict[str, GameEnv] = field(default_factory=dict)                    # by NFL team
    cascades: list[dict] = field(default_factory=list)
    injuries: dict[str, InjuryState] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    data_status: dict[str, str] = field(default_factory=dict)

    def adjustments_for(self, player_id: int) -> list[Adjustment]:
        p = self.projections.get(player_id)
        return p.adjustments if p else []


# ---------------------------------------------------------------------------
# injuries
# ---------------------------------------------------------------------------
def _sleeper_to_gsis(db_path: Optional[str]) -> dict[str, str]:
    with db.connect(db_path) as c:
        return {r["sleeper_id"]: r["gsis_id"] for r in c.execute("SELECT sleeper_id, gsis_id FROM id_crosswalk WHERE sleeper_id IS NOT NULL AND gsis_id IS NOT NULL")}


def collect_injuries(h: Hist, tw: int, players: list, gsis_of: dict[int, str], sleeper_index=None, news_events: Optional[list[dict]] = None,
                     db_path: Optional[str] = None) -> dict[str, InjuryState]:
    """Merge every injury source into one state per player (GSIS-keyed). Most severe status wins; all agreeing sources are listed."""
    out: dict[str, InjuryState] = {}

    def put(gsis, name, pos, team, status, source, practice="", long_term=False, games=None):
        if not gsis or status not in SEVERITY:
            return
        cur = out.get(gsis)
        if cur is None or SEVERITY[status] > SEVERITY[cur.status]:
            keep = cur.sources if cur and cur.status == status else []
            out[gsis] = InjuryState(gsis, name or (cur.name if cur else ""), pos or (cur.pos if cur else ""), team or (cur.team if cur else ""), status,
                                    practice or (cur.practice if cur else ""), keep + [source], long_term or bool(cur and cur.long_term), games or (cur.games_missed if cur else None))
        elif SEVERITY[status] == SEVERITY[cur.status]:
            if source not in cur.sources:
                cur.sources.append(source)
            cur.practice = cur.practice or practice
            cur.long_term = cur.long_term or long_term
            cur.games_missed = cur.games_missed or games

    # 1) NFL official report via nflverse (all positions, includes defenders and offensive linemen)
    for r in h.inj[h.inj.t == tw].itertuples():
        put(r.gsis, getattr(r, "full_name", ""), r.pos, ids.norm_team(r.team), r.report_status if r.report_status in SEVERITY else "", "NFL injury report (nflverse)", practice_code(r.practice_status))
    # 2) Sleeper (fresher than the weekly report; skill positions only)
    if sleeper_index is not None:
        s2g = _sleeper_to_gsis(db_path)
        for sid, d in sleeper_index.players.items():
            st = SLEEPER_STATUS.get(d.get("injury_status", ""))
            if st:
                put(d.get("gsis_id") or s2g.get(sid), d["name"], d["pos"], ids.norm_team(d["team"]), st, "Sleeper", long_term=d.get("injury_status") in ("IR", "PUP", "NFI", "Sus"))
    # 3) ESPN statuses on the slate
    for p in players:
        st = ESPN_STATUS.get(p.injury_status)
        if st and p.player_id in gsis_of:
            put(gsis_of[p.player_id], p.name, p.position, ids.norm_team(p.pro_team), st, "ESPN", long_term=p.injury_status in ("INJURY_RESERVE", "SUSPENSION"))
    # 4) parsed news (module 6): only what the article states
    for ev in news_events or []:
        st = NEWS_STATUS.get((ev.get("status") or "").lower())
        gm = ev.get("expected_games_missed")
        if st and ev.get("gsis"):
            put(ev["gsis"], ev.get("player", ""), ev.get("pos", ""), ev.get("team", ""), st, f"News: {ev.get('source_url') or 'ESPN'}",
                long_term=bool(gm and gm >= LONG_TERM_GAMES), games=gm)
    return out


# ---------------------------------------------------------------------------
# game environment
# ---------------------------------------------------------------------------
def build_game_env(h: Hist, season: int, week: int, odds_events: Optional[list[dict]], settings: EdgeSettings, db_path: Optional[str],
                   forecast_fn: Callable = fx.game_forecast) -> tuple[pd.DataFrame, dict[str, GameEnv], list[str]]:
    """One row per team playing this week with Vegas + weather columns the modules expect, plus display objects."""
    warnings: list[str] = []
    ctx = game_context(h)
    g = ctx[(ctx.season == season) & (ctx.week == week)].copy()
    sched = h.games[(h.games.season == season) & (h.games.week == week)].set_index("team")
    by_pair = {(e["home"], e["away"]): e for e in (odds_events or [])}
    envs: dict[str, GameEnv] = {}
    rows = []
    for r in g.itertuples():
        s = sched.loc[r.team] if r.team in sched.index else None
        spread, total, src = r.spread, r.total, "nflverse schedule"
        home, away = (r.team, r.opp_g) if r.home else (r.opp_g, r.team)
        ev = by_pair.get((home, away))
        if ev:
            spread = ev["spread_home_fav"] if r.home else -ev["spread_home_fav"]
            total, src = ev["total"], "odds-api"
        if pd.isna(spread) or pd.isna(total):
            spread = total = np.nan
            src = "missing"
        implied = total / 2 + spread / 2 if src != "missing" else np.nan
        x_imp = implied - (r.implied - r.x_imp) if src != "missing" else np.nan          # prev_implied = implied - x_imp (from game_context)
        wind = temp = np.nan
        wind15 = cold = 0.0
        env = GameEnv(r.team, r.opp_g, bool(r.home), None if src == "missing" else float(spread), None if src == "missing" else float(total),
                      None if src == "missing" else float(implied), None if src == "missing" else float(total / 2 - spread / 2), src,
                      f"{r.gameday} {r.gametime} ET", str(s["stadium"]) if s is not None else "")
        if s is not None and r.home:                                              # compute each game's forecast once, from the home side
            fc = forecast_fn(r.team, str(s["stadium"]) if s is not None else None, str(r.gameday), str(r.gametime), settings, db_path)
        else:
            fc = forecast_fn(r.opp_g, str(s["stadium"]) if s is not None else None, str(r.gameday), str(r.gametime), settings, db_path)
        if fc:
            env.roof, env.forecast_at = fc.get("roof", ""), fc.get("fetched_at")
            if fc.get("indoor"):
                env.weather_note = f"{fc['roof']}: no weather adjustment"
            else:
                wind, temp = fc["wind_mph"], fc["temp_f"]
                env.wind_mph, env.temp_f, env.precip_prob = wind, temp, fc.get("precip_prob")
                wind15, cold = float(wind >= 15), float(temp <= 25)
                env.weather_note = "forecast"
        else:
            env.weather_note = "no forecast available: no weather adjustment"
        envs[r.team] = env
        rows.append({"team": r.team, "x_imp": x_imp, "spread": spread, "implied": implied, "wind": wind, "temp": temp, "wind15": wind15, "cold": cold})
    if not rows:
        warnings.append(f"No NFL schedule rows found for {season} week {week}; game-environment edges are off.")
    return pd.DataFrame(rows), envs, warnings


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def run_engine(players: list, hist: Hist, season: int, week: int, *, sleeper_index=None, news_events: Optional[list[dict]] = None,
               odds_events: Optional[list[dict]] = None, settings: Optional[EdgeSettings] = None, params: Optional[dict] = None,
               db_path: Optional[str] = None, forecast_fn: Callable = fx.game_forecast, persist: bool = True) -> EngineResult:
    """`players`: PlayerInfo list (slate). Each player's `espn_week_proj` (or `week_proj` if unset) is the ESPN baseline."""
    t0 = time.time()
    s = settings or EdgeSettings()
    params = params or load_params()
    mods = params.get("modules", {})
    live = params.get("live_scale", {})
    tw = season * 100 + week
    res = EngineResult(season, week, time.time())
    if not mods:
        res.warnings.append("Edge parameters not found - run `python -m edge.backtest` to generate edge/params.json. No adjustments applied.")
        return res

    # --- slate -> GSIS
    gsis_of: dict[int, str] = {}
    for p in players:
        if p.position in SKILL:
            g = ids.resolve(p.player_id, p.name, p.pro_team, p.position, db_path)
            if g:
                gsis_of[p.player_id] = g
            else:
                res.warnings.append(f"No nflverse ID for {p.name}; no edges for him.")
    res.data_status["id_crosswalk"] = f"{len(gsis_of)} of {sum(1 for p in players if p.position in SKILL)} skill players matched"

    # --- injuries
    res.injuries = collect_injuries(hist, tw, players, gsis_of, sleeper_index, news_events, db_path)
    res.data_status["injuries"] = f"{len(res.injuries)} players on the combined injury list (NFL report + Sleeper + ESPN + news)"
    if not (hist.inj.t == tw).any():
        res.data_status["injuries"] += "; the NFL report for this week isn't published yet"

    # --- game environment
    genv, res.game_env, w = build_game_env(hist, season, week, odds_events, s, db_path, forecast_fn)
    res.warnings += w
    src = {e.lines_source for e in res.game_env.values()}
    res.data_status["vegas"] = ", ".join(sorted(src)) or "missing"
    res.data_status["weather"] = f"{sum(1 for e in res.game_env.values() if e.wind_mph is not None)} outdoor forecasts, " \
                                 f"{sum(1 for e in res.game_env.values() if e.weather_note.endswith('no weather adjustment') and e.roof)} indoor/retractable"

    # --- rows to project
    meta = {}
    for p in players:
        gid = gsis_of.get(p.player_id)
        base = p.espn_week_proj or p.week_proj
        if not gid or p.on_bye or base <= 0 or p.injury_status in ("OUT", "INJURY_RESERVE", "SUSPENSION"):
            continue
        team = ids.norm_team(p.pro_team)
        env = res.game_env.get(team)
        if env is None:
            continue
        meta[p.player_id] = dict(espn_id=p.player_id, gsis=gid, name=p.name, pos=p.position, team=team, opp=env.opp, t=tw, season=season, week=week, base=float(base))
    if not meta:
        res.warnings.append("No playable players on the slate (bye weeks or no schedule); nothing to adjust.")
        return res
    rows = pd.DataFrame(list(meta.values()))
    rows = rows.merge(genv, on="team", how="left")
    rows.index = range(len(rows))
    baselines = {int(r.espn_id): float(r.base) for r in rows.itertuples()}
    raw: list[Adjustment] = []
    now = time.time()

    def push(row, kind, delta, alpha_key, reason, source, conf, scope="week"):
        a = params["modules"].get(alpha_key, {}).get("alpha", 0.0)
        d = float(delta) * a * live.get(alpha_key, 1.0)
        if abs(d) >= MIN_ADJ and a > 0:
            raw.append(Adjustment(int(row.espn_id), season, week, kind, round(d, 3), reason, source, conf, now, None, scope))
        return d

    # --- vegas + weather
    vegas_src = {"odds-api": "Vegas consensus (The Odds API)", "nflverse schedule": "Vegas lines (nflverse schedule)"}
    if "vegas" in mods and mods["vegas"].get("alpha", 0) > 0:
        pred = Vegas(coefs=mods["vegas"].get("coefs", {})).predict(hist, rows)
        for i, r in enumerate(rows.itertuples()):
            if pred.at[i, "reason"]:
                push(r, "vegas", pred.at[i, "delta"], "vegas", pred.at[i, "reason"], vegas_src.get(res.game_env[r.team].lines_source, "Vegas lines"), pred.at[i, "confidence"])
    if "weather" in mods and mods["weather"].get("alpha", 0) > 0:
        pred = Weather(coefs=mods["weather"].get("coefs", {})).predict(hist, rows)
        for i, r in enumerate(rows.itertuples()):
            e = res.game_env[r.team]
            if pred.at[i, "reason"] and e.forecast_at:
                push(r, "weather", pred.at[i, "delta"], "weather", pred.at[i, "reason"] + f" (forecast from {time.strftime('%a %I:%M %p', time.localtime(e.forecast_at))})",
                     "Open-Meteo forecast", "low")

    # --- cascade
    if "cascade" in mods and mods["cascade"].get("alpha", 0) > 0:
        co = mods["cascade"].get("coefs", {})
        prep = prep_for(hist)
        flows, p_abs, scale = co.get("flows", {}), co.get("p_absent", {}), co.get("scale", {})
        by_team: dict[str, dict[str, tuple[float, str, InjuryState]]] = {}
        for g, st in res.injuries.items():
            by_team.setdefault(st.team, {})[g] = (p_for(p_abs, st.status, st.practice), "OUT" if st.status in ("Out", "Doubtful") else "QUESTIONABLE", st)
        gsis_to_espn = {v: k for k, v in gsis_of.items()}
        for team, absent in by_team.items():
            out = compute_team(prep, flows, team, tw, {g: v[0] for g, v in absent.items()})
            if not out:
                continue
            words = {g: v[1] for g, v in absent.items()}
            casc = {"team": team, "absent": [{"gsis": g, "name": prep.name_of.get(g) or v[2].name, "status": v[2].status, "p_out": round(v[0], 2), "long_term": v[2].long_term,
                                              "sources": v[2].sources} for g, v in absent.items() if prep.pos_of.get(g) in ("RB", "WR", "TE")], "beneficiaries": []}
            for g, info in out.items():
                pos = prep.pos_of.get(g)
                eid = gsis_to_espn.get(g)
                delta = info["delta"] * scale.get(pos, 0.5)
                reason, conf = explain(prep, info, words)
                causes = [absent[c[0]][2] for c in info["causes"] if c[0] in absent]
                src_txt = "Injury status: " + "; ".join(sorted({x for c in causes for x in c.sources})) + " | nflverse game history (with/without + flow rates)"
                casc["beneficiaries"].append({"gsis": g, "espn_id": eid, "name": prep.name_of.get(g, ""), "pos": pos, "weekly_pts": round(delta, 2), "reason": reason, "confidence": conf})
                if eid in meta:
                    row = rows[rows.espn_id == eid].iloc[0]
                    d = push(row, "cascade", delta, "cascade", reason, src_txt, conf)
                    if any(c.long_term for c in causes) and abs(d) >= MIN_ADJ:
                        raw.append(Adjustment(eid, season, week, "cascade", round(d * ROS_PERSIST, 3), "Rest of season: " + reason, src_txt, "low", now, None, "ros"))
            res.cascades.append(casc)

    # --- defense / OL injuries and pass rush
    if "defense" in mods and mods["defense"].get("alpha", 0) > 0 and mods["defense"].get("coefs", {}).get("features"):
        dmod = Defense(coefs=mods["defense"]["coefs"])
        dmod.live_status = {}
        for g, st in res.injuries.items():
            dmod.live_status.setdefault(st.team, {})[g] = (st.pos, st.status, st.practice)
        pred = dmod.predict(hist, rows)
        for i, r in enumerate(rows.itertuples()):
            if pred.at[i, "reason"]:
                push(r, "defense", pred.at[i, "delta"], "defense", pred.at[i, "reason"], "NFL injury report + snap history" + (" + play-by-play pressure rates" if "press" in dmod._active() else ""), "low")

    # --- regression signals (xFP gap) + tags
    sig = signals_asof(hist, [m["gsis"] for m in meta.values()] + [g for g in gsis_of.values()], tw)
    sig_by = sig.set_index("gsis") if len(sig) else pd.DataFrame(columns=["gap4", "dsnap"])
    for pid, g in gsis_of.items():
        if g in sig_by.index:
            gap, ds = sig_by.at[g, "gap4"], sig_by.at[g, "dsnap"] if "dsnap" in sig_by else np.nan
            tg = [(t, TAG_TEXT[t] + (f" (xFP gap {gap:+.1f} pts/game)" if t != "role growing" and gap == gap else "")) for t in tag_for(gap, ds)]
            if tg:
                res.tags[pid] = tg
    if "regression" in mods and mods["regression"].get("alpha", 0) > 0 and len(sig):
        rmod = Regression(coefs=mods["regression"].get("coefs", {}))
        rmod.override = sig
        pred = rmod.predict(hist, rows)
        for i, r in enumerate(rows.itertuples()):
            if pred.at[i, "reason"]:
                d = push(r, "regression", pred.at[i, "delta"], "regression", pred.at[i, "reason"], "nflverse ff_opportunity (expected fantasy points), last 4 games", "low")
                if abs(d) >= MIN_ADJ:
                    raw.append(Adjustment(int(r.espn_id), season, week, "regression", round(d * 0.5, 3), "Rest of season: " + pred.at[i, "reason"],
                                          "nflverse ff_opportunity, last 4 games", "low", now, None, "ros"))

    # --- rest-of-season schedule (not backtested: small, shrunk, flagged)
    raw += _schedule_adjustments(hist, rows, season, week, now)

    # --- cap against ESPN baselines, persist, summarize
    proj = store.build_and_store(baselines, raw, season, week, s, db_path) if persist else _cap_only(baselines, raw, season, week, s)
    res.projections = proj
    for pid, base in baselines.items():
        res.projections.setdefault(pid, AdjustedProjection(pid, season, week, base, [], "No edge data for this player - using ESPN as is."))
    for a in raw:
        if a.scope == "ros":
            res.ros[a.player_id] = res.ros.get(a.player_id, 0.0) + a.delta_points
            res.ros_notes.setdefault(a.player_id, []).append(a.reason)
    res.data_status["engine"] = f"{len(raw)} adjustments for {len(baselines)} players in {time.time() - t0:.1f}s"
    return res


def _cap_only(baselines, raw, season, week, s):
    from edge.types import apply_cap
    by: dict[int, list[Adjustment]] = {}
    for a in raw:
        by.setdefault(a.player_id, []).append(a)
    out = {}
    for pid, adjs in by.items():
        wk = apply_cap(baselines.get(pid, 0.0), [a for a in adjs if a.scope == "week"], s.cap_pct, s.cap_floor)
        out[pid] = AdjustedProjection(pid, season, week, baselines.get(pid, 0.0), wk)
    return out


def _schedule_adjustments(h: Hist, rows: pd.DataFrame, season: int, week: int, now: float) -> list[Adjustment]:
    """Rest-of-season schedule strength from the REMAINING opponents' points allowed (this season, shrunk toward the league mean).

    NOT backtested, so it is deliberately tiny (max +/-3% of the ESPN baseline per game), low confidence, and labeled as such."""
    g = h.games[h.games.season == season]
    played = g[(g.week < week) & g.total.notna()]
    if played.empty:
        return []
    sc = played.assign(pa=played.opp_implied)                     # without scores in `games`, use implied points allowed as the proxy
    pa = sc.groupby("opp")["implied"].mean()                      # what each defense's opponents were expected to score ... shrunk below
    league = float(pa.mean()) if len(pa) else 22.5
    remain = g[(g.week >= week)].groupby("team")["opp"].apply(list)
    out = []
    for r in rows.itertuples():
        opps = remain.get(r.team, [])
        if len(opps) < 3:
            continue
        ratio = np.mean([pa.get(o, league) / league for o in opps])
        factor = 1.0 + float(np.clip(0.25 * (ratio - 1.0), -0.03, 0.03))
        d = r.base * (factor - 1.0)
        if abs(d) >= MIN_ADJ:
            out.append(Adjustment(int(r.espn_id), season, week, "schedule", round(d, 3), f"Rest-of-season schedule: remaining opponents' offenses are projected {'higher' if ratio > 1 else 'lower'} than average "
                                  f"({ratio:.2f}x), shrunk to {factor - 1:+.1%}. Not backtested.", "nflverse schedule lines", "low", now, None, "ros"))
    return out
