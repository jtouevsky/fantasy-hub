"""Environment-driven configuration. Secrets only ever come from `.env`."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

PLACEHOLDERS = {"", "your_espn_s2_cookie_here", "{YOUR-SWID-COOKIE-HERE}", "your_anthropic_api_key_here"}


def _real(value: str | None) -> str:
    value = (value or "").strip()
    return "" if value in PLACEHOLDERS else value


@dataclass(frozen=True)
class Config:
    espn_s2: str
    swid: str
    league_id: int
    year: int
    team_id: int
    anthropic_api_key: str
    anthropic_model: str
    cache_ttl: int
    db_path: str

    def __repr__(self) -> str:  # never leak secrets into logs/tracebacks
        return (
            f"Config(league_id={self.league_id}, year={self.year}, team_id={self.team_id}, "
            f"espn_s2={'set' if self.espn_s2 else 'MISSING'}, swid={'set' if self.swid else 'MISSING'}, "
            f"anthropic_key={'set' if self.anthropic_api_key else 'MISSING'}, model={self.anthropic_model})"
        )

    def missing_espn(self) -> list[str]:
        """Names of required ESPN settings that are unset (names only, never values)."""
        missing = []
        if not self.league_id:
            missing.append("LEAGUE_ID")
        if not self.team_id:
            missing.append("TEAM_ID")
        # Public leagues work without cookies, but private ones need both.
        if not self.espn_s2:
            missing.append("ESPN_S2")
        if not self.swid:
            missing.append("SWID")
        return missing


def _int(name: str, default: int = 0) -> int:
    raw = _real(os.getenv(name))
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def load_config() -> Config:
    return Config(
        espn_s2=_real(os.getenv("ESPN_S2")),
        swid=_real(os.getenv("SWID")),
        league_id=_int("LEAGUE_ID"),
        year=_int("YEAR", 2026),
        team_id=_int("TEAM_ID"),
        anthropic_api_key=_real(os.getenv("ANTHROPIC_API_KEY")),
        anthropic_model=_real(os.getenv("ANTHROPIC_MODEL")) or "claude-sonnet-5-5",
        cache_ttl=_int("CACHE_TTL_SECONDS", 300),
        db_path=os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fantasy_hub.db")),
    )
