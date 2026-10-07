"""Fantasy points under THIS league's scoring, computed from nflverse raw stats.

The league's scoringItems come from ESPN (statId -> points) and are cached in SQLite, so the backtest scores players
exactly as your league does. Falls back to standard PPR if the league hasn't been read yet.
"""
from __future__ import annotations

import json
from typing import Optional

import db

# ESPN stat id -> nflverse weekly-stats columns (all columns are summed, each worth the item's points)
STAT_COLUMNS: dict[int, list[str]] = {
    3: ["passing_yards"], 4: ["passing_tds"], 19: ["passing_2pt_conversions"], 20: ["passing_interceptions"],
    24: ["rushing_yards"], 25: ["rushing_tds"], 26: ["rushing_2pt_conversions"],
    42: ["receiving_yards"], 43: ["receiving_tds"], 44: ["receiving_2pt_conversions"], 53: ["receptions"],
    63: ["fumble_recovery_tds"], 72: ["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"],
    101: ["special_teams_tds"],                                    # kick/punt return TDs (102 is the same nflverse column)
    80: ["fg_made_0_19", "fg_made_20_29", "fg_made_30_39"], 77: ["fg_made_40_49"], 198: ["fg_made_50_59"], 201: ["fg_made_60_"],
    85: ["fg_missed"], 86: ["pat_made"],
}
STANDARD_PPR = [
    {"statId": 3, "points": 0.04}, {"statId": 4, "points": 4.0}, {"statId": 19, "points": 2.0}, {"statId": 20, "points": -2.0},
    {"statId": 24, "points": 0.1}, {"statId": 25, "points": 6.0}, {"statId": 26, "points": 2.0},
    {"statId": 42, "points": 0.1}, {"statId": 43, "points": 6.0}, {"statId": 44, "points": 2.0}, {"statId": 53, "points": 1.0},
    {"statId": 63, "points": 6.0}, {"statId": 72, "points": -2.0}, {"statId": 101, "points": 6.0},
]
_KEY = "league_scoring"


def save_scoring(items: list[dict], path: Optional[str] = None) -> None:
    keep = [{"statId": int(i["statId"]), "points": float(i.get("points", 0) or 0)} for i in items]
    db.setting_set(_KEY, json.dumps(keep), path)


def load_scoring(path: Optional[str] = None) -> list[dict]:
    raw = db.setting_get(_KEY, "", path)
    return json.loads(raw) if raw else STANDARD_PPR


def weights(items: Optional[list[dict]] = None, path: Optional[str] = None) -> dict[str, float]:
    """nflverse column -> points per unit under the league's scoring."""
    w: dict[str, float] = {}
    seen_special = False
    for it in items if items is not None else load_scoring(path):
        sid, pts = int(it["statId"]), float(it["points"])
        if sid == 102:
            continue
        if sid == 101:
            seen_special = True
        for col in STAT_COLUMNS.get(sid, []):
            w[col] = w.get(col, 0.0) + pts
    return w


def points(df, w: dict[str, float]):
    """Vectorised points for a pandas DataFrame of nflverse weekly stats (missing columns count as 0)."""
    total = 0.0
    for col, pts in w.items():
        if col in df.columns:
            total = total + df[col].fillna(0) * pts
    return total
