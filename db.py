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
