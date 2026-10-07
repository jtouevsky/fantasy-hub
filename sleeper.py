"""Sleeper's free public API (no auth): injury details and trending adds/drops.

Sleeper IDs differ from ESPN IDs and Sleeper's `espn_id` is often empty, so players are
matched on normalized name + position (D/ST by team abbreviation)."""
from __future__ import annotations

import re
from typing import Callable, Optional

import requests

import db
from models import PlayerInfo

BASE = "https://api.sleeper.app/v1"
PLAYERS_TTL = 24 * 3600
TRENDING_TTL = 600
_KEEP_POS = {"QB", "RB", "WR", "TE", "K", "DEF"}
_TEAM_FIX = {"WSH": "WAS", "WAS": "WAS"}          # ESPN says WSH, Sleeper says WAS
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm_name(name: str) -> str:
    n = re.sub(r"[^a-z ]", "", name.lower().replace("-", " "))
    return re.sub(r"\s+", " ", _SUFFIX.sub("", n)).strip()


def _team(abbrev: str) -> str:
    return _TEAM_FIX.get(abbrev, abbrev)


def _get(path: str, params: Optional[dict] = None):
    r = requests.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def load_players(db_path: Optional[str] = None, fetch: Callable = _get) -> dict[str, dict]:
    """Slim {sleeper_id: {...}} for fantasy-relevant players, cached for 24h."""
    cached = db.cache_get("sleeper:players", PLAYERS_TTL, db_path)
    if cached:
        return cached
    raw = fetch("/players/nfl")
    slim = {}
    for pid, d in raw.items():
        pos = d.get("position")
        if pos not in _KEEP_POS or not (d.get("active") or pos == "DEF"):
            continue
        slim[pid] = {
            "name": d.get("full_name") or f"{d.get('first_name', '')} {d.get('last_name', '')}".strip(),
            "pos": "D/ST" if pos == "DEF" else pos, "team": d.get("team") or "",
            "status": d.get("status") or "", "injury_status": d.get("injury_status") or "",
            "injury_body_part": d.get("injury_body_part") or "", "injury_notes": d.get("injury_notes") or "",
        }
    db.cache_set("sleeper:players", slim, db_path)
    return slim


def trending(kind: str = "add", hours: int = 24, limit: int = 50, db_path: Optional[str] = None,
             fetch: Callable = _get) -> list[dict]:
    """Trending adds/drops: [{'player_id', 'count'}]."""
    key = f"sleeper:trending:{kind}:{hours}"
    cached = db.cache_get(key, TRENDING_TTL, db_path)
    if cached is None:
        cached = fetch(f"/players/nfl/trending/{kind}", {"lookback_hours": hours, "limit": limit})
        db.cache_set(key, cached, db_path)
    return cached


class SleeperIndex:
    """Lookup from ESPN-side PlayerInfo to Sleeper data."""

    def __init__(self, players: dict[str, dict]):
        self.players = players
        self._by_key: dict[tuple[str, str], str] = {}
        for sid, d in players.items():
            key = (d["team"], "D/ST") if d["pos"] == "D/ST" else (norm_name(d["name"]), d["pos"])
            self._by_key.setdefault(key, sid)

    def find(self, p: PlayerInfo) -> Optional[str]:
        key = (_team(p.pro_team), "D/ST") if p.position == "D/ST" else (norm_name(p.name), p.position)
        return self._by_key.get(key)

    def info(self, p: PlayerInfo) -> Optional[dict]:
        sid = self.find(p)
        return self.players.get(sid) if sid else None

    def injury(self, p: PlayerInfo) -> dict:
        d = self.info(p) or {}
        return {k: d.get(k, "") for k in ("injury_status", "injury_body_part", "injury_notes", "status")}


def trending_counts(index: SleeperIndex, kind: str = "add", db_path: Optional[str] = None,
                    fetch: Callable = _get) -> dict[str, int]:
    """{sleeper_id: add_count} so callers can look players up via index.find()."""
    return {t["player_id"]: int(t["count"]) for t in trending(kind, db_path=db_path, fetch=fetch)}
