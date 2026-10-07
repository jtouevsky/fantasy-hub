"""SQLite persistence for adjustments."""
from __future__ import annotations

from typing import Iterable, Optional

import db
from edge.types import Adjustment, AdjustedProjection, apply_cap
from edge.settings import EdgeSettings


def save(adjs: Iterable[Adjustment], season: int, week: int, path: Optional[str] = None, replace_types: Optional[set[str]] = None) -> None:
    """Replace the stored adjustments for this season/week (optionally only the given types) with `adjs`."""
    adjs = list(adjs)
    with db.connect(path) as c:
        if replace_types is None:
            c.execute("DELETE FROM adjustments WHERE season=? AND week=?", (season, week))
        else:
            marks = ",".join("?" * len(replace_types))
            c.execute(f"DELETE FROM adjustments WHERE season=? AND week=? AND type IN ({marks})", (season, week, *replace_types))
        c.executemany(
            "INSERT INTO adjustments(player_id,season,week,type,delta_points,raw_delta,reason,source,created_at,confidence,scope) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(a.player_id, a.season, a.week, a.type, a.delta_points, a.raw_delta, a.reason, a.source, a.created_at, a.confidence, a.scope) for a in adjs])


def load(season: int, week: int, player_id: Optional[int] = None, path: Optional[str] = None, scope: Optional[str] = None) -> list[Adjustment]:
    q, args = "SELECT * FROM adjustments WHERE season=? AND week=?", [season, week]
    if player_id is not None:
        q += " AND player_id=?"; args.append(player_id)
    if scope:
        q += " AND scope=?"; args.append(scope)
    with db.connect(path) as c:
        rows = c.execute(q + " ORDER BY ABS(delta_points) DESC", args).fetchall()
    return [Adjustment(r["player_id"], r["season"], r["week"], r["type"], r["delta_points"], r["reason"], r["source"], r["confidence"],
                       r["created_at"], r["raw_delta"], r["scope"]) for r in rows]


def projection_for(player_id: int, espn_proj: float, season: int, week: int, path: Optional[str] = None) -> AdjustedProjection:
    adjs = load(season, week, player_id, path, scope="week")
    return AdjustedProjection(player_id, season, week, espn_proj, adjs, "" if adjs else "No edge data for this player - using ESPN as is.")


def build_and_store(baselines: dict[int, float], raw: Iterable[Adjustment], season: int, week: int, settings: Optional[EdgeSettings] = None,
                    path: Optional[str] = None, replace_types: Optional[set[str]] = None) -> dict[int, AdjustedProjection]:
    """Group raw adjustments by player, apply the cap against each player's ESPN baseline, persist, and return projections."""
    s = settings or EdgeSettings()
    by_player: dict[int, list[Adjustment]] = {}
    for a in raw:
        by_player.setdefault(a.player_id, []).append(a)
    capped: list[Adjustment] = []
    out: dict[int, AdjustedProjection] = {}
    for pid, adjs in by_player.items():
        week_adjs = [a for a in adjs if a.scope == "week"]
        ros_adjs = [a for a in adjs if a.scope != "week"]
        week_adjs = apply_cap(baselines.get(pid, 0.0), week_adjs, s.cap_pct, s.cap_floor)
        capped += week_adjs + ros_adjs
        out[pid] = AdjustedProjection(pid, season, week, baselines.get(pid, 0.0), week_adjs)
    save(capped, season, week, path, replace_types)
    return out
