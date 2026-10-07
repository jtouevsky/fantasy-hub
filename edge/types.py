"""Adjustment records and the per-player cap."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Optional

CONFIDENCE = ("low", "med", "high")
TYPES = ("cascade", "defense", "vegas", "weather", "regression", "trend", "news")


@dataclass
class Adjustment:
    player_id: int                 # ESPN player id
    season: int
    week: int
    type: str
    delta_points: float            # what is added to the ESPN projection (after the cap)
    reason: str                    # plain English
    source: str                    # where the numbers came from (dataset / API / news item)
    confidence: str = "low"
    created_at: float = field(default_factory=time.time)
    raw_delta: Optional[float] = None   # before capping
    scope: str = "week"            # 'week' (this game) or 'ros' (rest of season, per game)

    def __post_init__(self):
        if self.confidence not in CONFIDENCE:
            raise ValueError(f"confidence must be one of {CONFIDENCE}")
        if self.raw_delta is None:
            self.raw_delta = self.delta_points


def cap_limit(baseline: float, cap_pct: float = 0.35, floor: float = 6.0) -> float:
    """Largest total |adjustment| allowed for a player-week.

    cap_pct * max(baseline, floor): the floor stops the cap from crushing the most valuable case (a 2-point backup
    who becomes the starter). Set floor=0 for a strict percentage-of-baseline cap."""
    return cap_pct * max(baseline, floor, 0.0)


def apply_cap(baseline: float, adjustments: Iterable[Adjustment], cap_pct: float = 0.35, floor: float = 6.0) -> list[Adjustment]:
    """Scale all adjustments proportionally if their sum exceeds the cap. Keeps each one's direction and relative size,
    and records the uncapped value in `raw_delta`."""
    adjs = list(adjustments)
    total = sum(a.raw_delta if a.raw_delta is not None else a.delta_points for a in adjs)
    limit = cap_limit(baseline, cap_pct, floor)
    scale = 1.0 if abs(total) <= limit or total == 0 else limit / abs(total)
    for a in adjs:
        raw = a.raw_delta if a.raw_delta is not None else a.delta_points
        a.raw_delta = raw
        a.delta_points = round(raw * scale, 2)
    return adjs


@dataclass
class AdjustedProjection:
    player_id: int
    season: int
    week: int
    espn: float
    adjustments: list[Adjustment] = field(default_factory=list)
    note: str = ""                 # e.g. "No edge data available - using ESPN as is"

    @property
    def total(self) -> float:
        return round(sum(a.delta_points for a in self.adjustments), 2)

    @property
    def adjusted(self) -> float:
        return round(max(self.espn + self.total, 0.0), 2)

    def label(self) -> str:
        return f"ESPN {self.espn:.1f} → Adjusted {self.adjusted:.1f}" if self.adjustments else f"ESPN {self.espn:.1f} (no adjustment)"
