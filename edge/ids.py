"""ID crosswalk ESPN <-> Sleeper <-> nflverse (GSIS). Stable IDs everywhere; name matching is a last resort and always logged."""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import db
from sleeper import norm_name

log = logging.getLogger("edge.ids")
_TEAM_ALIASES = {"WAS": "WSH", "JAC": "JAX", "LA": "LAR", "ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU", "SD": "LAC", "OAK": "LV", "STL": "LAR"}


def norm_team(t: str) -> str:
    t = (t or "").upper()
    return _TEAM_ALIASES.get(t, t)


def refresh_crosswalk(path: Optional[str] = None, frame=None) -> int:
    """Rebuild the crosswalk from nflverse's ff_playerids (maintained by the ffverse project). Returns rows stored."""
    if frame is None:
        import nflreadpy as nfl
        frame = nfl.load_ff_playerids().to_pandas()
    df = frame[frame["gsis_id"].notna() | frame["espn_id"].notna() | frame["sleeper_id"].notna()]
    rows = []
    for r in df.itertuples():
        espn = None if r.espn_id != r.espn_id or r.espn_id is None else int(float(r.espn_id))
        slp = None if r.sleeper_id != r.sleeper_id or r.sleeper_id is None else str(int(float(r.sleeper_id)))
        rows.append((espn, slp, r.gsis_id if r.gsis_id == r.gsis_id else None, r.pfr_id if r.pfr_id == r.pfr_id else None,
                     r.name, norm_name(r.name or ""), r.position, norm_team(r.team or "")))
    with db.connect(path) as c:
        c.execute("DELETE FROM id_crosswalk")
        c.executemany("INSERT INTO id_crosswalk VALUES(?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def _ensure(path: Optional[str]) -> None:
    with db.connect(path) as c:
        n = c.execute("SELECT COUNT(*) AS n FROM id_crosswalk").fetchone()["n"]
    if n == 0:
        refresh_crosswalk(path)


def gsis_for_espn(espn_id: int, path: Optional[str] = None) -> Optional[str]:
    _ensure(path)
    with db.connect(path) as c:
        r = c.execute("SELECT gsis_id FROM id_crosswalk WHERE espn_id=? AND gsis_id IS NOT NULL LIMIT 1", (espn_id,)).fetchone()
    return r["gsis_id"] if r else None


def espn_for_gsis(gsis: str, path: Optional[str] = None) -> Optional[int]:
    _ensure(path)
    with db.connect(path) as c:
        r = c.execute("SELECT espn_id FROM id_crosswalk WHERE gsis_id=? AND espn_id IS NOT NULL LIMIT 1", (gsis,)).fetchone()
    return r["espn_id"] if r else None


def gsis_for_sleeper(sleeper_id: str, path: Optional[str] = None) -> Optional[str]:
    _ensure(path)
    with db.connect(path) as c:
        r = c.execute("SELECT gsis_id FROM id_crosswalk WHERE sleeper_id=? AND gsis_id IS NOT NULL LIMIT 1", (str(sleeper_id),)).fetchone()
    return r["gsis_id"] if r else None


def resolve(espn_id: int, name: str, team: str, position: str, path: Optional[str] = None) -> Optional[str]:
    """GSIS id for an ESPN player. Primary: the ID crosswalk. Fallback: normalized name + team + position, with a logged warning."""
    g = gsis_for_espn(espn_id, path)
    if g:
        return g
    with db.connect(path) as c:
        rows = c.execute("SELECT gsis_id, team, position FROM id_crosswalk WHERE merge_name=? AND gsis_id IS NOT NULL", (norm_name(name),)).fetchall()
        pos_ok = [r for r in rows if (r["position"] or "") == position]
        team_ok = [r for r in pos_ok if r["team"] == norm_team(team)]
        pick = team_ok or (pos_ok if len(pos_ok) == 1 else [])
        gsis = pick[0]["gsis_id"] if pick else None
        if gsis:
            log.warning("ID crosswalk miss for ESPN %s (%s, %s, %s): matched by name+team+position -> %s", espn_id, name, team, position, gsis)
        else:
            log.warning("No nflverse match for ESPN %s (%s, %s, %s)", espn_id, name, team, position)
        c.execute("INSERT INTO match_log VALUES(?,?,?,?,?,?,?)", (time.time(), espn_id, name, team, position, gsis, "name+team+pos" if gsis else "unmatched"))
    return gsis


def match_report(path: Optional[str] = None) -> dict:
    with db.connect(path) as c:
        rows = c.execute("SELECT method, COUNT(*) n FROM match_log GROUP BY method").fetchall()
    return {r["method"]: r["n"] for r in rows}
