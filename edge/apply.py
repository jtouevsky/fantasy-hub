"""Apply an EngineResult to PlayerInfo objects so every existing screen (optimizer, waivers, trades, rows) sees adjusted numbers.

ESPN's own projection is always preserved in `espn_week_proj`; `week_proj` becomes the adjusted number. Idempotent.
"""
from __future__ import annotations

import time

from models import PlayerInfo


def apply_result(players: list[PlayerInfo], res) -> int:
    n = 0
    for p in players:
        if not p.espn_week_proj:
            p.espn_week_proj = p.week_proj
        p.week_proj, p.edge, p.edge_ros, p.tags, p.context = p.espn_week_proj, [], 0.0, [], []
        proj = res.projections.get(p.player_id)
        if proj and proj.adjustments:
            p.edge = [{"type": a.type, "delta": a.delta_points, "raw": a.raw_delta, "reason": a.reason, "source": a.source, "confidence": a.confidence, "at": a.created_at}
                      for a in proj.adjustments]
            p.week_proj = round(max(p.espn_week_proj + sum(a.delta_points for a in proj.adjustments), 0.0), 2)
            n += 1
        p.edge_ros = round(res.ros.get(p.player_id, 0.0), 3)
        p.tags = [list(t) for t in res.tags.get(p.player_id, [])]
        p.context = list(res.context.get(p.player_id, []))
    return n


def clear(players: list[PlayerInfo]) -> None:
    for p in players:
        if p.espn_week_proj:
            p.week_proj = p.espn_week_proj
        p.espn_week_proj, p.edge, p.edge_ros, p.tags, p.context = 0.0, [], 0.0, [], []
