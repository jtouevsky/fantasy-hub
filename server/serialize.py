"""JSON view-models. All logic stays in the existing Python modules; this file only reshapes their results for the web client."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import assets
import ui
from ctx import Ctx
from models import PlayerInfo, TeamInfo

FANTASY_COLORS = ["#4f74e3", "#c2410c", "#0f766e", "#7c3aed", "#b45309", "#be185d", "#15803d", "#0369a1", "#a21caf", "#b91c1c", "#4d7c0f", "#475569"]


def nfl_color(ctx: Ctx, abbr: str) -> str:
    return assets.usable_color(assets.team(abbr, ctx.cfg.db_path).color)


def edge_rows(p: PlayerInfo) -> list[dict]:
    return [{"type": a["type"], "label": ui.EDGE_LABEL.get(a["type"], a["type"]), "delta": round(a["delta"], 2), "raw": round(a.get("raw", a["delta"]), 2),
             "reason": a["reason"], "source": a["source"], "confidence": a["confidence"],
             "at": datetime.fromtimestamp(a["at"]).strftime("%a %-I:%M %p") if a.get("at") else ""} for a in sorted(p.edge, key=lambda a: -abs(a["delta"]))]


def context_rows(p: PlayerInfo) -> list[dict]:
    return [{"kind": c["kind"], "label": ui.EDGE_LABEL.get(c["kind"], c["kind"]), "pts": round(c["pts"], 2), "text": c["text"], "source": c.get("source", ""),
             "confidence": c.get("confidence", "low")} for c in p.context]


def status_label(p: PlayerInfo) -> str:
    if p.on_bye:
        return "Bye week"
    s = p.injury_status
    return "" if s == "ACTIVE" else s.replace("_", " ").title().replace("Injury Reserve", "IR")


def player(ctx: Ctx, p: PlayerInfo, slot: Optional[str] = None, detail: bool = False) -> dict:
    d = {
        "id": p.player_id, "name": p.name, "pos": p.position, "team": p.pro_team, "slot": slot if slot is not None else p.lineup_slot,
        "status": p.injury_status, "statusLabel": status_label(p), "onBye": p.on_bye, "out": p.is_out, "risky": p.is_risky,
        "proj": round(p.week_proj, 1), "espnProj": round(p.espn_week_proj or p.week_proj, 1), "hasEdge": p.has_edge, "edgeTotal": p.edge_total,
        "actualPpg": round(p.actual_ppg, 1), "weekPts": round(p.week_points, 1), "totalPts": round(p.total_points, 1), "gp": p.games_played,
        "opp": p.opponent, "kick": ui.kick_label(p), "lock": ui.lock_state(p), "owner": p.owner_team_id, "owned": p.percent_owned,
        "watch": p.player_id in ctx.watchlist, "color": nfl_color(ctx, p.pro_team), "tags": [list(t) for t in p.tags],
        "bye": p.bye_week or None,
        "img": None if p.position == "D/ST" else {"s": assets.headshot_url(p.player_id, 120), "l": assets.headshot_url(p.player_id, 360)},
    }
    if detail:
        d["edge"], d["context"], d["edgeRos"] = edge_rows(p), context_rows(p), p.edge_ros
    return d


def fteam(ctx: Ctx, t: TeamInfo) -> dict:
    return {"id": t.team_id, "name": t.name, "abbrev": t.abbrev, "owner": t.owner_label, "first": (t.owners[0].first_name if t.owners else ""),
            "record": t.record, "standing": t.standing, "pf": round(t.points_for), "pa": round(t.points_against), "playoffPct": t.playoff_pct,
            "color": FANTASY_COLORS[(t.team_id - 1) % len(FANTASY_COLORS)], "logo": f"/api/img/fteam/{t.team_id}?v={abs(hash(t.logo)) % 10**6}" if t.logo else None,
            "me": t.team_id == ctx.me.team_id}


def game_env(env) -> Optional[dict]:
    if env is None:
        return None
    fav = "" if env.spread is None else (f"{env.team} favored by {env.spread:.1f}" if env.spread > 0 else f"{env.opp} favored by {-env.spread:.1f}" if env.spread < 0 else "Pick'em")
    return {"team": env.team, "opp": env.opp, "kickoff": env.kickoff, "fav": fav, "total": env.total, "implied": env.implied, "oppImplied": env.opp_implied,
            "windMph": env.wind_mph, "tempF": env.temp_f, "precip": env.precip_prob, "weatherNote": env.weather_note, "linesSource": env.lines_source,
            "forecastAt": datetime.fromtimestamp(env.forecast_at).strftime("%a %-I:%M %p") if env.forecast_at and env.wind_mph is not None else None}


def news_event(ev: dict) -> dict:
    return {"player": ev.get("player", ""), "status": ev.get("status"), "type": ev.get("event_type", "news"), "games": ev.get("expected_games_missed"),
            "summary": ev.get("summary", ""), "raw": (ev.get("raw_text") or "")[:700], "url": ev.get("source_url"), "at": str(ev.get("published_at", ""))[:16].replace("T", " "),
            "beneficiaries": ev.get("beneficiaries") or [], "espnId": ev.get("player_espn_id")}


def swap(ctx: Ctx, s) -> dict:
    return {"in": player(ctx, s.player_in), "out": player(ctx, s.player_out) if s.player_out else None, "slot": s.slot, "gain": round(s.gain, 1), "reason": s.reason,
            "fromEdge": s.from_edge, "espnGain": round(s.espn_gain, 1), "edgeNote": s.edge_note, "action": s.action(), "edgeLabel": ui.edge_label(s.player_in)}


def move(ctx: Ctx, m) -> dict:
    return {**m.to_dict(), "addP": player(ctx, m.add), "dropP": player(ctx, m.drop) if m.drop else None, "starts": m.starts, "weeks": m.weeks,
            "action": m.action(), "blocked": m.blocked}


def stream(ctx: Ctx, sp) -> dict:
    return {**sp.to_dict(), "bestP": player(ctx, sp.best) if sp.best else None, "currentP": player(ctx, sp.current) if sp.current else None}


def moveset(ctx: Ctx, ms) -> dict:
    return {"moves": [move(ctx, m) for m in ms.moves], "streams": [stream(ctx, s) for s in ms.streams], "empty": ms.empty, "reason": ms.no_move_reason}


def matchup_state(ctx: Ctx) -> str:
    """Pregame / In progress / Games complete, from real kickoff times of both starting lineups."""
    from datetime import timedelta
    starters = [p for t in (ctx.me, ctx.opp) if t for p in t.roster if p.lineup_slot not in ("BE", "IR") and ui.kickoff(p)]
    if not starters:
        return "Pregame"
    now = datetime.now()
    started = [ui.kickoff(p) <= now for p in starters]
    if not any(started):
        return "Pregame"
    if all(ui.kickoff(p) + timedelta(hours=4) <= now for p in starters):
        return "Games complete"
    return "In progress"


def scoreboard(ctx: Ctx) -> Optional[dict]:
    snap, me, opp = ctx.snap, ctx.me, ctx.opp
    m = snap.matchup_for(me.team_id)
    if not (m and opp):
        return None
    home = m.home_team_id == me.team_id
    mine, theirs = (m.home_score, m.away_score) if home else (m.away_score, m.home_score)
    mproj, tproj = (m.home_proj, m.away_proj) if home else (m.away_proj, m.home_proj)
    return {"week": snap.week, "state": matchup_state(ctx), "me": fteam(ctx, me), "opp": fteam(ctx, opp), "myScore": mine, "oppScore": theirs, "myProj": round(mproj, 1), "oppProj": round(tproj, 1)}


def age_seconds(ctx: Ctx) -> Optional[float]:
    return None if ctx.demo else max(datetime.now().timestamp() - ctx.snap.fetched_at, 0)
