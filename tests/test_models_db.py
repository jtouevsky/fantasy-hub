import demo_data
import db
from models import LeagueSnapshot


def test_snapshot_json_roundtrip():
    snap = demo_data.build_demo_snapshot()
    again = LeagueSnapshot.from_dict(snap.to_dict())
    assert again.to_dict() == snap.to_dict()
    assert again.my_team.name == "Demo Team 1"
    assert again.matchup_for(1).opponent_of(1) == 2


def test_cache_ttl_and_recommendation_log():
    path = ":memory:"  # each connect() is a fresh DB, so use a temp file for persistence
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.db")
        db.cache_set("k", {"a": 1}, path)
        assert db.cache_get("k", 60, path) == {"a": 1}
        assert db.cache_get("k", -1, path) is None          # expired
        rid = db.log_recommendation("trade", "Give A for B", {"split": 60}, week=5, path=path)
        db.set_outcome(rid, "good", path)
        rows = db.list_recommendations(path=path)
        assert rows[0]["summary"] == "Give A for B" and rows[0]["outcome"] == "good"
