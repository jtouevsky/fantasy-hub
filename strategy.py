"""My strategy: persisted settings that every recommendation (waivers, moves, trades, the AI assistant) must respect."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Optional

import db

KEY = "strategy"


@dataclass
class Strategy:
    # streaming: re-pick the best option EVERY week, ranked on THIS week (never rest-of-season)
    stream_dst: bool = True
    stream_k: bool = False
    stream_swap_gain: float = 2.0            # only swap a streamer if this week's gain clears this many points
    # roster construction (position caps; the number of QBs/TEs is relative to the league's real starting slots)
    max_qb: int = 2
    max_dst: int = 1
    max_k: int = 1
    max_te_extra: int = 1                    # TEs beyond the starting slots, unless he is elite
    # protection
    recent_days: int = 7                     # don't churn players I added in the last N days...
    recent_override_gain: float = 5.0        # ...unless the gain is at least this many pts/week AND there is new injury news
    # evaluation
    playoff_weight: float = 1.5              # weight of fantasy-playoff weeks in rest-of-season value
    min_gain_week: float = 1.0               # a move must add at least this much this week OR...
    min_gain_ros: float = 4.0                # ...this many rest-of-season points
    speculative_extra_gain: float = 3.0      # extra gain demanded when the projection is a one-week outlier
    explanation: str = "Short"               # "Short" (no definitions) or "Beginner" (explain D/ST, IR, bye...)
    # trade tuning
    accept_threshold: float = 0.0            # logit above which an offer counts as "plausible"
    extra: dict = field(default_factory=dict)

    @property
    def streaming(self) -> set[str]:
        return ({"D/ST"} if self.stream_dst else set()) | ({"K"} if self.stream_k else set())

    def caps(self, starter_slots: dict[str, int]) -> dict[str, int]:
        """Hard roster caps by position. A position the league has no starting slot for (e.g. K here) gets cap 0: never add one."""
        qb_starters = starter_slots.get("QB", 0) + starter_slots.get("OP", 0)
        caps = {"QB": max(self.max_qb, qb_starters + 1) if qb_starters else 0,
                "D/ST": self.max_dst if starter_slots.get("D/ST") else 0,
                "K": self.max_k if starter_slots.get("K") else 0,
                "TE": starter_slots.get("TE", 0) + starter_slots.get("WR/TE", 0) + self.max_te_extra if starter_slots.get("TE") else 0}
        return caps


def load(db_path: Optional[str] = None) -> Strategy:
    raw = db.setting_get(KEY, "", db_path)
    if not raw:
        return Strategy()
    try:
        data = json.loads(raw)
    except ValueError:
        return Strategy()
    known = {f.name for f in fields(Strategy)}
    return Strategy(**{k: v for k, v in data.items() if k in known})


def save(s: Strategy, db_path: Optional[str] = None) -> None:
    db.setting_set(KEY, json.dumps(asdict(s)), db_path)


def prompt_block(s: Strategy, starter_slots: dict[str, int], week: int) -> str:
    """Plain-text strategy context for the AI assistant's system prompt."""
    caps = s.caps(starter_slots)
    return (f"MY STRATEGY (hard rules; never recommend anything that breaks them): current week {week}. Starting slots: "
            + ", ".join(f"{n}x {k}" for k, n in starter_slots.items()) + ". "
            f"Streaming positions (re-pick weekly on THIS week's adjusted projection, swap only if this-week gain >= {s.stream_swap_gain:g} pts, otherwise 'keep your current one'): "
            f"{', '.join(sorted(s.streaming)) or 'none'}. Roster caps: " + ", ".join(f"{k} <= {v}" for k, v in caps.items()) + ". "
            f"Do not churn players added in the last {s.recent_days} days. Explanations: {s.explanation} "
            f"({'define terms like D/ST, IR and bye' if s.explanation == 'Beginner' else 'no definitions'}); at most 1-2 lines per move.")
