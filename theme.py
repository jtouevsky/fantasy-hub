"""Theme preferences (mode + accent team), persisted in SQLite. The visual tokens live in web/src/styles.css."""
from __future__ import annotations

from typing import Optional

import db

MODES = ["System", "Light", "Dark"]

def get_mode(db_path: Optional[str] = None) -> str:
    m = db.setting_get("theme_mode", "System", db_path)
    return m if m in MODES else "System"


def set_mode(mode: str, db_path: Optional[str] = None) -> None:
    if mode in MODES:
        db.setting_set("theme_mode", mode, db_path)


def get_accent_team(db_path: Optional[str] = None) -> str:
    return db.setting_get("accent_team", "", db_path)


def set_accent_team(abbr: str, db_path: Optional[str] = None) -> None:
    db.setting_set("accent_team", abbr, db_path)
