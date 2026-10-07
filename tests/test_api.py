"""Every API endpoint answers on demo data (the same engines the UI used before the migration)."""
import pytest
from fastapi.testclient import TestClient

import ctx as cx


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    for k in ("ctx", "ctx_data", "edge", "model", "hub"):
        cx.STORE[k] = None
    cx.STORE["chat"] = {"api": [], "session": None, "ui": []}
    from server.main import app
    return TestClient(app, raise_server_exceptions=False)


GETS = ["/api/bootstrap", "/api/overview", "/api/team", "/api/matchup", "/api/league", "/api/players", "/api/trades/meta", "/api/strategy", "/api/edge", "/api/log", "/api/chat", "/api/news"]


@pytest.mark.parametrize("path", GETS)
def test_get_endpoints(client, path):
    r = client.get(path)
    assert r.status_code == 200, (path, r.text[:300])


def test_bootstrap_shape(client):
    b = client.get("/api/bootstrap").json()
    assert b["league"]["week"] and b["me"]["name"] and len(b["teams"]) >= 2 and b["search"] and "nfl" in b


def test_player_detail_history_and_watch(client):
    pid = client.get("/api/bootstrap").json()["search"][0]["id"]
    d = client.get(f"/api/player/{pid}").json()
    assert d["id"] == pid and d["todo"]["mode"] in ("mine", "fa", "other")
    assert client.get(f"/api/player/{pid}/history").status_code == 200
    assert client.post(f"/api/watch/{pid}").json()["watching"] is True


def test_trade_flow_and_negotiation_log(client):
    meta = client.get("/api/trades/meta").json()
    other = next(t for t in meta["teams"] if not t["me"])
    parsed = client.post("/api/trades/parse", json={"text": "find me a receiver at 60/40"}).json()
    assert parsed["split"] == 60
    res = client.post("/api/trades/search", json={"partner": other["id"], "split": 60, "max": 3}).json()
    assert "results" in res
    ev = client.post("/api/trades/evaluate", json={"partner": other["id"], "give": [meta["mine"][0]["id"]], "get": [other["players"][0]["id"]]}).json()
    assert ev["verdictMe"] in ("good", "marginal", "no") and ev["label"] in ("likely", "coin flip", "unlikely") and ev["pitch"]
    r = client.post("/api/trades/negotiations", json={"team": other["id"], "give": ev["giveIds"], "get": ev["getIds"], "response": "rejected", "note": "t"})
    assert r.status_code == 200
    assert client.get(f"/api/trades/negotiations?team={other['id']}").json()["rows"]


def test_strategy_roundtrip_and_settings(client):
    s = client.get("/api/strategy").json()["strategy"]
    assert client.put("/api/strategy", json={"stream_swap_gain": 3.5}).status_code == 200
    assert client.get("/api/strategy").json()["strategy"]["stream_swap_gain"] == 3.5
    assert client.put("/api/settings", json={"mode": "Dark"}).status_code == 200
    assert client.get("/api/bootstrap").json()["settings"]["mode"] == "Dark"


def test_navigation_does_not_recompute(client):
    client.get("/api/overview")
    c1 = cx.STORE["ctx"]
    for p in ("/api/team", "/api/players", "/api/overview", "/api/league"):
        client.get(p)
    assert cx.STORE["ctx"] is c1                                  # same context object: nothing rebuilt while navigating
