"""Small pure formatting helpers shared by the API and the agent (no UI framework involved)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from models import PlayerInfo

EDGE_LABEL = {"cascade": "Injury cascade", "defense": "Opposing defense / OL injuries", "vegas": "Game environment (Vegas)", "weather": "Weather",
              "regression": "Opportunity vs. production", "schedule": "Rest-of-season schedule", "news": "News"}
TAG_ICON = {"buy low": "trending_up", "sell high": "trending_down", "role growing": "moving"}


def edge_label(p: PlayerInfo) -> str:
    """'ESPN 12.4 → Adjusted 14.9' (or just the ESPN number when nothing was adjusted)."""
    if p.has_edge:
        return f"ESPN {p.espn_week_proj:.1f} → Adjusted {p.week_proj:.1f}"
    return f"ESPN {p.week_proj:.1f}"


def _clock(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %-I:%M %p") if ts else ""


def kickoff(p: PlayerInfo) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(p.game_time) if p.game_time else None
    except ValueError:
        return None


def kick_label(p: PlayerInfo) -> str:
    k = kickoff(p)
    if not k:
        return "Bye" if p.on_bye else ""
    return k.strftime("%a %-I:%M %p")


def lock_state(p: PlayerInfo, now: Optional[datetime] = None) -> str:
    """'bye' | 'locked' (game has started) | 'open' | ''."""
    if p.on_bye:
        return "bye"
    k = kickoff(p)
    if not k:
        return ""
    return "locked" if k <= (now or datetime.now()) else "open"
