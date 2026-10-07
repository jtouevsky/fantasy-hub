"""Report card: every recommended add / start is recorded and later scored on what actually happened.

A recommendation counts as a HIT when the player we said to add (or start) scored more fantasy points than the player he was supposed to replace
over the weeks played since the recommendation (up to MAX_WEEKS completed weeks, after which it is final). Scored with the league's scoring from
nflverse weekly stats; players nflverse does not cover (D/ST, K) are not tracked.
"""
from __future__ import annotations

import time
from typing import Optional

import pandas as pd

import db

MAX_WEEKS = 3


def record(db_path: Optional[str], season: int, week: int, kind: str, add, drop, gsis_of: dict[int, str], pred_gain: float, confidence: str = "", summary: str = "") -> bool:
    """Idempotent: the same (week, kind, add, drop) is stored once. Returns True if it was new."""
    if add.position not in ("QB", "RB", "WR", "TE"):
        return False
    with db.connect(db_path) as c:
        cur = c.execute("INSERT OR IGNORE INTO move_tracking (created_ts, season, week, kind, add_id, add_name, add_gsis, drop_id, drop_name, drop_gsis, position, pred_gain, confidence, summary) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), season, week, kind, add.player_id, add.name, gsis_of.get(add.player_id), drop.player_id if drop else -1, drop.name if drop else None,
                         gsis_of.get(drop.player_id) if drop else None, add.position, round(pred_gain, 2), confidence, summary[:300]))
        return cur.rowcount > 0


def _points(weekly: pd.DataFrame, gsis: Optional[str], season: int, weeks: list[int]) -> tuple[float, int]:
    if not gsis:
        return 0.0, 0
    w = weekly[(weekly.gsis == gsis) & (weekly.season == season) & weekly.week.isin(weeks)]
    return float(w.pts.sum()), int(len(w))


def score(db_path: Optional[str], weekly: pd.DataFrame, season: int, current_week: int) -> int:
    """Score every open or still-running recommendation whose week has completed. Returns how many rows changed."""
    n = 0
    with db.connect(db_path) as c:
        rows = c.execute("SELECT * FROM move_tracking WHERE season=? AND week<? AND weeks_scored<?", (season, current_week, MAX_WEEKS)).fetchall()
        for r in rows:
            done = [wk for wk in range(r["week"], min(current_week, r["week"] + MAX_WEEKS))]
            a, na = _points(weekly, r["add_gsis"], season, done)
            d, nd = _points(weekly, r["drop_gsis"], season, done) if r["drop_gsis"] else (0.0, 0)
            if not done or (na == 0 and nd == 0):
                continue                                         # nothing played yet (or no data): stay open
            c.execute("UPDATE move_tracking SET weeks_scored=?, add_pts=?, drop_pts=?, hit=? WHERE id=?", (len(done), round(a, 1), round(d, 1), int(a > d), r["id"]))
            n += 1
    return n


def report(db_path: Optional[str]) -> dict:
    with db.connect(db_path) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM move_tracking ORDER BY week DESC, id DESC").fetchall()]
    scored = [r for r in rows if r["hit"] is not None]
    by_week: dict[int, list[dict]] = {}
    for r in scored:
        by_week.setdefault(r["week"], []).append(r)
    weeks = [{"week": w, "n": len(v), "hits": sum(x["hit"] for x in v), "rate": round(100 * sum(x["hit"] for x in v) / len(v))} for w, v in sorted(by_week.items())]
    for r in rows:
        r["diff"] = round(r["add_pts"] - r["drop_pts"], 1) if r["hit"] is not None else None
    return {"total": len(rows), "scored": len(scored), "hits": sum(r["hit"] for r in scored), "rate": round(100 * sum(r["hit"] for r in scored) / len(scored)) if scored else None,
            "weeks": weeks, "rows": rows[:100], "pending": len(rows) - len(scored)}
