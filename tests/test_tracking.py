import pandas as pd

import tracking
from models import PlayerInfo


def P(pid, name, pos="WR"):
    return PlayerInfo(pid, name, pos, "KC", "ACTIVE", "BE", [pos])


def weekly(rows):
    return pd.DataFrame([dict(gsis=g, season=2026, week=w, pts=p) for g, w, p in rows])


def test_recommendation_is_recorded_once_and_scored_after_the_week_completes(tmp_path):
    db = str(tmp_path / "t.db")
    add, drop = P(1, "Add Guy"), P(2, "Drop Guy")
    gs = {1: "G1", 2: "G2"}
    assert tracking.record(db, 2026, 5, "add", add, drop, gs, 6.0, "medium", "x") is True
    assert tracking.record(db, 2026, 5, "add", add, drop, gs, 6.0) is False                # idempotent
    w = weekly([("G1", 5, 15.0), ("G2", 5, 8.0), ("G1", 6, 4.0), ("G2", 6, 9.0)])
    assert tracking.score(db, w, 2026, 5) == 0                                              # week 5 not finished yet
    assert tracking.score(db, w, 2026, 6) == 1
    r = tracking.report(db)
    assert r["hits"] == 1 and r["rate"] == 100 and r["rows"][0]["diff"] == 7.0 and r["weeks"] == [{"week": 5, "n": 1, "hits": 1, "rate": 100}]
    assert tracking.score(db, w, 2026, 7) == 1                                              # a second completed week updates the running comparison
    r = tracking.report(db)
    assert r["rows"][0]["weeks_scored"] == 2 and r["rows"][0]["diff"] == 2.0
    assert r["rows"][0]["add_pts"] == 19.0 and r["rows"][0]["drop_pts"] == 17.0 and r["hits"] == 1


def test_a_miss_and_untracked_positions(tmp_path):
    db = str(tmp_path / "t.db")
    tracking.record(db, 2026, 4, "start", P(3, "In"), P(4, "Out"), {3: "G3", 4: "G4"}, 3.0)
    assert tracking.record(db, 2026, 4, "add", P(5, "Defense", "D/ST"), None, {}, 2.0) is False       # D/ST isn't covered by weekly stats
    tracking.score(db, weekly([("G3", 4, 5.0), ("G4", 4, 14.0)]), 2026, 5)
    r = tracking.report(db)
    assert r["hits"] == 0 and r["scored"] == 1 and r["rate"] == 0 and r["rows"][0]["diff"] == -9.0
