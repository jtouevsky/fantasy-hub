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


LOGO_PX = 160            # one resized variant serves every badge size up to ~80px at 2x
FIT = 0.72               # the logo's longest side fills this share of the badge's inner diameter


def team_logo(abbr: str, db_path: Optional[str] = None) -> str:
    """Uniform logo file for a team: ESPN's 'scoreboard' variant (consistent art; NYJ's default is a 4096px wordmark),
    resized by ESPN's image service to LOGO_PX so every badge downloads a few KB."""
    t = team(abbr, db_path)
    if t.abbr == "NFL":
        return ""
    return (f"https://a.espncdn.com/combiner/i?img=/i/teamlogos/nfl/500/scoreboard/{t.abbr.lower()}.png&w={LOGO_PX}&h={LOGO_PX}")


def _alpha_bounds(url: str) -> Optional[tuple[float, float, float, float]]:
    """(cx, cy, w, h) of the visible (non-transparent) pixels as fractions of the image, or None."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(requests.get(url, timeout=15).content)).convert("RGBA")
        box = im.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
        if not box:
            return None
        W, H = im.size
        return ((box[0] + box[2]) / 2 / W, (box[1] + box[3]) / 2 / H, (box[2] - box[0]) / W, (box[3] - box[1]) / H)
    except Exception:
        return None


def logo_geometry(db_path: Optional[str] = None) -> dict[str, tuple[float, float, float, float]]:
    """Visible-pixel bounds per team logo (cached 30 days). Many logo files carry uneven transparent padding, so
    centering the *box* is not enough; badges shift/scale the image by these numbers to center the *artwork*."""
    cached = db.cache_get("assets:logo_geom_v2", TEAMS_TTL, db_path)
    if cached is None:
        teams = nfl_teams(db_path)
        with cf.ThreadPoolExecutor(8) as ex:
            geo = dict(zip(teams, ex.map(lambda ab: _alpha_bounds(team_logo(ab, db_path)), teams)))
        cached = {k: list(v) for k, v in geo.items() if v}
        if cached:
            db.cache_set("assets:logo_geom_v2", cached, db_path)
    return {k: tuple(v) for k, v in cached.items()}


def logo_transform(bounds: Optional[tuple[float, float, float, float]]) -> tuple[float, float, float]:
    """(dx%, dy%, scale) that centers the artwork in the badge and sizes its longest side to FIT of the inner diameter.
    With the image filling the badge's content box, scaling by k about the center moves the artwork center from c to
    0.5 + k*(c-0.5); translating by k*(0.5-c) puts it back exactly at the middle."""
    if not bounds:
        return 0.0, 0.0, 1.0
    cx, cy, w, h = bounds
    k = FIT / max(w, h, 0.05)
    return round(100 * k * (0.5 - cx), 2), round(100 * k * (0.5 - cy), 2), round(k, 4)


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
