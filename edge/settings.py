"""Edge-engine configuration: environment overrides + tuned module parameters."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

_PARAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.json")


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class EdgeSettings:
    cap_pct: float = field(default_factory=lambda: _f("EDGE_CAP_PCT", 0.35))        # |total adjustment| <= cap_pct * baseline ...
    cap_floor: float = field(default_factory=lambda: _f("EDGE_CAP_FLOOR", 6.0))     # ... where baseline is at least this many points
    odds_api_key: str = field(default_factory=lambda: os.getenv("ODDS_API_KEY", "").strip())
    odds_ttl_hours: float = field(default_factory=lambda: _f("ODDS_TTL_HOURS", 12.0))   # free tier ~500 req/month: refresh at most twice a day
    weather_ttl_minutes: float = field(default_factory=lambda: _f("WEATHER_TTL_MINUTES", 60.0))


def load_params() -> dict:
    """Per-module scale factors tuned by `python -m edge.backtest` (0 = module off, 1 = full strength)."""
    try:
        with open(_PARAMS, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_params(params: dict) -> None:
    with open(_PARAMS, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, sort_keys=True)
