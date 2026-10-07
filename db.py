"""SQLite: a TTL cache for API snapshots and a log of every recommendation made."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from config import load_config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    fetched_at REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,          -- ESPN player id (what the app uses everywhere)
    season INTEGER NOT NULL, week INTEGER NOT NULL,
    type TEXT NOT NULL,                  -- cascade | defense | vegas | weather | regression | schedule | news
    delta_points REAL NOT NULL,          -- AFTER the per-player cap
    raw_delta REAL NOT NULL,             -- before the cap
    reason TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL, confidence TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'week'   -- week | ros
);
CREATE INDEX IF NOT EXISTS adj_lookup ON adjustments(season, week, player_id);
CREATE TABLE IF NOT EXISTS id_crosswalk (
    espn_id INTEGER, sleeper_id TEXT, gsis_id TEXT, pfr_id TEXT, name TEXT, merge_name TEXT, position TEXT, team TEXT
);
CREATE INDEX IF NOT EXISTS xw_espn ON id_crosswalk(espn_id);
CREATE INDEX IF NOT EXISTS xw_gsis ON id_crosswalk(gsis_id);
CREATE INDEX IF NOT EXISTS xw_sleeper ON id_crosswalk(sleeper_id);
CREATE TABLE IF NOT EXISTS match_log (
    created_at REAL NOT NULL, espn_id INTEGER, name TEXT, team TEXT, position TEXT, matched_gsis TEXT, method TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_events (
    news_key TEXT PRIMARY KEY, player_espn_id INTEGER, raw_text TEXT NOT NULL, parsed TEXT, source_url TEXT, published_at TEXT,
    parsed_at REAL, error TEXT
);
CREATE TABLE IF NOT EXISTS negotiations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, team_id INTEGER NOT NULL, manager TEXT NOT NULL,
    give_ids TEXT NOT NULL, get_ids TEXT NOT NULL, give_names TEXT NOT NULL, get_names TEXT NOT NULL,
    response TEXT NOT NULL,              -- accepted | rejected | countered | pending
    note TEXT, model_logit REAL           -- the model's pre-response logit (None if unknown), used for the Bayesian tendency update
);
CREATE TABLE IF NOT EXISTS move_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT, created_ts REAL NOT NULL, season INTEGER NOT NULL, week INTEGER NOT NULL,
    kind TEXT NOT NULL,                  -- add | start
    add_id INTEGER NOT NULL, add_name TEXT NOT NULL, add_gsis TEXT, drop_id INTEGER, drop_name TEXT, drop_gsis TEXT, position TEXT,
    pred_gain REAL, confidence TEXT, summary TEXT,
    weeks_scored INTEGER DEFAULT 0, add_pts REAL, drop_pts REAL, hit INTEGER,      -- filled in as weeks complete
    UNIQUE (season, week, kind, add_id, drop_id)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    week INTEGER,
    kind TEXT NOT NULL,          -- trade | lineup | waiver | news | chat
    summary TEXT NOT NULL,
    details TEXT,                -- JSON blob (tool inputs/outputs, numbers)
    source TEXT NOT NULL,        -- 'agent' or 'ui'
    outcome TEXT                 -- filled in later by you: good | bad | ignored | notes
);
"""


def _path(path: Optional[str]) -> str:
    return path or load_config().db_path


@contextmanager
def connect(path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    p = _path(path)
    if p != ":memory:":
        os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def cache_get(key: str, ttl: float, path: Optional[str] = None) -> Optional[Any]:
    """Return the cached JSON value if younger than `ttl` seconds, else None."""
    with connect(path) as c:
        row = c.execute("SELECT fetched_at, payload FROM cache WHERE key=?", (key,)).fetchone()
    if row and (time.time() - row["fetched_at"]) <= ttl:
        return json.loads(row["payload"])
    return None


def cache_age(key: str, path: Optional[str] = None) -> Optional[float]:
    with connect(path) as c:
        row = c.execute("SELECT fetched_at FROM cache WHERE key=?", (key,)).fetchone()
    return (time.time() - row["fetched_at"]) if row else None


def cache_set(key: str, value: Any, path: Optional[str] = None) -> None:
    with connect(path) as c:
        c.execute(
            "INSERT INTO cache(key, fetched_at, payload) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload",
            (key, time.time(), json.dumps(value)),
        )


def cache_clear(prefix: str = "", path: Optional[str] = None) -> None:
    with connect(path) as c:
        c.execute("DELETE FROM cache WHERE key LIKE ?", (prefix + "%",))


def log_recommendation(
    kind: str, summary: str, details: Any = None, week: Optional[int] = None,
    source: str = "agent", path: Optional[str] = None,
) -> int:
    with connect(path) as c:
        cur = c.execute(
            "INSERT INTO recommendations(created_at, week, kind, summary, details, source) VALUES(?,?,?,?,?,?)",
            (time.time(), week, kind, summary, json.dumps(details) if details is not None else None, source),
        )
        return int(cur.lastrowid)


def list_recommendations(limit: int = 200, path: Optional[str] = None) -> list[dict]:
    with connect(path) as c:
        rows = c.execute("SELECT * FROM recommendations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def set_outcome(rec_id: int, outcome: str, path: Optional[str] = None) -> None:
    with connect(path) as c:
        c.execute("UPDATE recommendations SET outcome=? WHERE id=?", (outcome, rec_id))


def setting_get(key: str, default: str = "", path: Optional[str] = None) -> str:
    with connect(path) as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def setting_set(key: str, value: str, path: Optional[str] = None) -> None:
    with connect(path) as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
