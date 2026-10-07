"""Game-day weather from Open-Meteo (free, no key). Cached per stadium/day for WEATHER_TTL_MINUTES; the forecast timestamp is kept for display."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import requests

import db
from edge.settings import EdgeSettings
from edge.stadiums import locate

URL = "https://api.open-meteo.com/v1/forecast"


def kickoff_utc(gameday: str, gametime: str) -> Optional[datetime]:
    """nflverse gameday/gametime are US Eastern."""
    try:
        local = datetime.fromisoformat(f"{gameday}T{gametime}").replace(tzinfo=ZoneInfo("America/New_York"))
        return local.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def pick_hours(payload: dict, kickoff: datetime, hours: int = 3) -> Optional[dict]:
    """Average the forecast over the first `hours` of the game (Open-Meteo times are UTC with timezone=UTC)."""
    h = payload.get("hourly", {})
    times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h.get("time", [])]
    idx = [i for i, t in enumerate(times) if kickoff - timedelta(minutes=30) <= t < kickoff + timedelta(hours=hours)]
    if not idx:
        return None
    avg = lambda key: sum(h[key][i] for i in idx if h[key][i] is not None) / max(len([i for i in idx if h[key][i] is not None]), 1)
    return {"wind_mph": round(avg("wind_speed_10m"), 1), "gust_mph": round(max(h["wind_gusts_10m"][i] or 0 for i in idx), 1),
            "temp_f": round(avg("temperature_2m"), 1), "precip_prob": round(max(h["precipitation_probability"][i] or 0 for i in idx)),
            "precip_mm": round(sum(h["precipitation"][i] or 0 for i in idx), 2)}


def game_forecast(home_team: str, stadium: Optional[str], gameday: str, gametime: str, settings: Optional[EdgeSettings] = None,
                  db_path: Optional[str] = None, fetch=None) -> Optional[dict]:
    """Forecast dict (with 'fetched_at' and 'roof') for a game, or None if unknown/too far out. Dome/retractable -> roof flag only."""
    s = settings or EdgeSettings()
    loc = locate(home_team, stadium)
    ko = kickoff_utc(gameday, gametime)
    if not loc or not ko:
        return None
    lat, lon, roof, name = loc
    if roof != "outdoor":
        return {"roof": roof, "stadium": name, "fetched_at": time.time(), "indoor": True}
    key = f"edge:wx:{lat:.3f}:{lon:.3f}:{ko.date()}"
    cached = db.cache_get(key, s.weather_ttl_minutes * 60, db_path)
    if cached is None:
        try:
            params = {"latitude": lat, "longitude": lon, "wind_speed_unit": "mph", "temperature_unit": "fahrenheit", "timezone": "UTC", "forecast_days": 16,
                      "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation_probability,precipitation"}
            payload = fetch() if fetch else requests.get(URL, params=params, timeout=20).json()
            picked = pick_hours(payload, ko)
        except Exception:
            return None
        if not picked:
            return None
        cached = {**picked, "roof": roof, "stadium": name, "fetched_at": time.time(), "indoor": False}
        db.cache_set(key, cached, db_path)
    return cached
