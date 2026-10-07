"""Vegas lines: The Odds API (free tier, key in .env) with aggressive caching; falls back to nflverse schedule lines.

Free tier ~500 credits/month; cost = markets x regions per call. We request spreads+totals for one region = 2 credits, and
refresh at most every ODDS_TTL_HOURS (default 12), so ~4 credits/day. Remaining quota is recorded from response headers.
"""
from __future__ import annotations

import statistics
from typing import Optional

import requests

import db
from edge.ids import norm_team
from edge.settings import EdgeSettings

URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
CACHE_KEY = "edge:odds"


def parse_events(events: list[dict], name_to_abbr: dict[str, str]) -> list[dict]:
    """Consensus (median across bookmakers) spread and total per game.

    Returns [{home, away, commence, spread_home_fav, total, n_books}] where spread_home_fav > 0 means the HOME team is favored
    (the same sign convention as nflverse `spread_line`)."""
    out = []
    for ev in events:
        home, away = name_to_abbr.get(ev.get("home_team", "")), name_to_abbr.get(ev.get("away_team", ""))
        if not home or not away:
            continue
        spreads, totals = [], []
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") == "spreads":
                    for o in mk.get("outcomes", []):
                        if o.get("name") == ev["home_team"] and o.get("point") is not None:
                            spreads.append(-float(o["point"]))            # home -3.5 means home favored by 3.5
                elif mk.get("key") == "totals":
                    pts = [float(o["point"]) for o in mk.get("outcomes", []) if o.get("point") is not None]
                    if pts:
                        totals.append(pts[0])
        if spreads and totals:
            out.append({"home": norm_team(home), "away": norm_team(away), "commence": ev.get("commence_time", ""),
                        "spread_home_fav": statistics.median(spreads), "total": statistics.median(totals), "n_books": len(spreads)})
    return out


def get_odds(settings: Optional[EdgeSettings] = None, name_to_abbr: Optional[dict[str, str]] = None, db_path: Optional[str] = None,
             fetch=None) -> Optional[list[dict]]:
    """Cached consensus lines, or None when no API key is configured / the call failed (caller falls back to nflverse)."""
    s = settings or EdgeSettings()
    if not s.odds_api_key:
        return None
    cached = db.cache_get(CACHE_KEY, s.odds_ttl_hours * 3600, db_path)
    if cached is not None:
        return cached
    try:
        if fetch is None:
            r = requests.get(URL, params={"apiKey": s.odds_api_key, "regions": "us", "markets": "spreads,totals", "oddsFormat": "american", "dateFormat": "iso"}, timeout=20)
            r.raise_for_status()
            events = r.json()
            db.setting_set("odds_requests_remaining", r.headers.get("x-requests-remaining", ""), db_path)
            db.setting_set("odds_requests_used", r.headers.get("x-requests-used", ""), db_path)
        else:
            events = fetch()
        parsed = parse_events(events, name_to_abbr or {})
    except Exception:
        stale = db.cache_get(CACHE_KEY, 10 ** 9, db_path)          # a stale answer beats no answer; never raise into the UI
        return stale
    db.cache_set(CACHE_KEY, parsed, db_path)
    return parsed


def quota(db_path: Optional[str] = None) -> dict:
    return {"remaining": db.setting_get("odds_requests_remaining", "", db_path), "used": db.setting_get("odds_requests_used", "", db_path)}
