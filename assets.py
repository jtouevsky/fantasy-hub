"""Team branding and player imagery, keyed by stable IDs (never by scraping names).

* NFL team names / abbreviations / colors / logos come from ESPN's public team directory (cached 30 days).
* Player headshots come from ESPN's CDN by ESPN player id, which is the same id the fantasy API uses.
  Every image URL is verified server-side once (cached), so a missing photo becomes a clean fallback.
"""
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass
from typing import Iterable, Optional

import requests

import db

TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
TEAMS_TTL = 30 * 86400
IMAGE_TTL = 14 * 86400
NEUTRAL = "6b7280"
# ESPN fantasy uses WSH; the team directory uses WSH too, but other feeds say WAS / JAC.
ALIASES = {"WAS": "WSH", "JAC": "JAX", "LA": "LAR", "ARZ": "ARI"}


@dataclass(frozen=True)
class NflTeam:
    abbr: str
    name: str            # Kansas City Chiefs
    short: str           # Chiefs
    color: str           # hex without '#'
    alt: str
    logo: str


_FALLBACK = NflTeam("NFL", "NFL", "NFL", NEUTRAL, "ffffff", "")


def _norm(abbr: str) -> str:
    a = (abbr or "").upper()
    return ALIASES.get(a, a)


def nfl_teams(db_path: Optional[str] = None) -> dict[str, NflTeam]:
    cached = db.cache_get("assets:nfl_teams", TEAMS_TTL, db_path)
    if cached is None:
        try:
            raw = requests.get(TEAMS_URL, timeout=15).json()["sports"][0]["leagues"][0]["teams"]
            cached = [{
                "abbr": t["team"]["abbreviation"], "name": t["team"]["displayName"], "short": t["team"].get("shortDisplayName", ""),
                "color": t["team"].get("color") or NEUTRAL, "alt": t["team"].get("alternateColor") or "ffffff",
                "logo": next((l["href"] for l in t["team"].get("logos", []) if "default" in l.get("rel", [])), ""),
            } for t in raw]
            db.cache_set("assets:nfl_teams", cached, db_path)
        except Exception:
            cached = db.cache_get("assets:nfl_teams", 10 ** 9, db_path) or []     # stale is better than nothing
    return {_norm(t["abbr"]): NflTeam(_norm(t["abbr"]), t["name"], t["short"], t["color"], t["alt"], t["logo"]) for t in cached}


def team(abbr: str, db_path: Optional[str] = None) -> NflTeam:
    return nfl_teams(db_path).get(_norm(abbr), _FALLBACK)


def team_logo(abbr: str, db_path: Optional[str] = None) -> str:
    t = team(abbr, db_path)
    return t.logo or (f"https://a.espncdn.com/i/teamlogos/nfl/500/{t.abbr.lower()}.png" if t.abbr != "NFL" else "")


# ---- colors ----------------------------------------------------------------
def _rgb(hexcolor: str) -> tuple[int, int, int]:
    h = hexcolor.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def luminance(hexcolor: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in _rgb(hexcolor))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def on_color(hexcolor: str) -> str:
    """Readable text color (white/near-black) for text placed on `hexcolor`."""
    return "#ffffff" if luminance(hexcolor) < 0.45 else "#111418"


def usable_color(hexcolor: str) -> str:
    """Some team colors are near-white/black; keep them from vanishing against glass."""
    l = luminance(hexcolor)
    return "#" + (NEUTRAL if l > 0.82 or l < 0.01 else hexcolor.lstrip("#"))


# ---- images ----------------------------------------------------------------
def headshot_url(player_id: int, width: int = 120) -> str:
    h = round(width * 0.73)
    return f"https://a.espncdn.com/combiner/i?img=/i/headshots/nfl/players/full/{int(player_id)}.png&w={width}&h={h}"


def _exists(url: str) -> bool:
    try:
        return requests.head(url, timeout=8, allow_redirects=True).status_code == 200
    except requests.RequestException:
        return False


def verified(urls: Iterable[str], db_path: Optional[str] = None) -> dict[str, bool]:
    """{url: loads?} - checks each unseen URL once (in parallel) and remembers the answer."""
    urls = list(dict.fromkeys(u for u in urls if u))
    known = db.cache_get("assets:image_ok", IMAGE_TTL, db_path) or {}
    todo = [u for u in urls if u not in known]
    if todo:
        with cf.ThreadPoolExecutor(16) as ex:
            for u, ok in zip(todo, ex.map(_exists, todo)):
                known[u] = ok
        db.cache_set("assets:image_ok", known, db_path)
    return {u: known.get(u, False) for u in urls}


def initials(name: str) -> str:
    parts = [p for p in name.replace(".", " ").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()
