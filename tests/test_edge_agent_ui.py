import json

import agent
import demo_data
import ui
from edge.engine import EngineResult, GameEnv
from models import PlayerInfo
from valuation import ValueModel


def _tools(tmp_path):
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    me, kaden = snap.my_team, snap.find_team("Kaden")
    star = max(me.roster, key=lambda p: p.week_proj)
    star.espn_week_proj, star.week_proj = star.week_proj, star.week_proj + 3.1
    star.edge = [{"type": "cascade", "delta": 3.1, "raw": 4.4, "reason": "Chuba Hubbard OUT -> +7.0 carries -> +3.1 pts (med confidence, 2-game with/without sample)",
                  "source": "NFL injury report (nflverse); nflverse game history", "confidence": "med", "at": 1.0}]
    star.edge_ros = 0.9
    buy, sell = kaden.roster[0], kaden.roster[1]
    buy.tags, sell.tags = [["buy low", "xFP outran production"]], [["sell high", "production outran xFP"]]
    res = EngineResult(2026, 5, 0.0)
    res.cascades = [{"team": "KC", "absent": [{"gsis": "G1", "name": "Their RB1", "status": "Out", "p_out": 1.0, "long_term": False, "sources": ["Sleeper"]}],
                     "beneficiaries": [{"gsis": "G2", "espn_id": 5, "name": "Backup RB", "pos": "RB", "weekly_pts": 3.2, "reason": "r", "confidence": "med"}]}]
    res.game_env = {"KC": GameEnv("KC", "BUF", True, -2.5, 47.0, 22.25, 24.75, "nflverse schedule", "2026-10-11 16:25 ET", "GEHA Field", "outdoor", 18.0, 40.0, 10, 1.0e9, "forecast")}
    t = agent.AgentTools(snap, ValueModel(snap, fas), lambda pos, n: [p for p in fas if pos in (None, p.position)], None, None, None, str(tmp_path / "a.db"), res, [])
    return t, star, buy, sell


def test_get_edges_shows_espn_vs_adjusted_with_source_and_confidence(tmp_path):
    t, star, *_ = _tools(tmp_path)
    out, err = t.call("get_edges", {"player_or_team": star.name})
    assert not err
    row = out["players"][0]
    assert row["espn_projection"] != row["adjusted_projection"] and row["total_adjustment"] == 3.1
    a = row["adjustments"][0]
    assert a["type"] == "cascade" and a["confidence"] == "med" and "nflverse" in a["source"] and a["uncapped_points"] == 4.4 and "Hubbard" in a["reason"]
    assert row["rest_of_season_edge_points_per_game"] == 0.9
    out, err = t.call("get_edges", {"player_or_team": "Jordan"})                            # a fantasy team resolves by owner first name
    assert not err and star.name in [p["name"] for p in out["players"]]
    out, err = t.call("get_edges", {"player_or_team": star.name, "week": 9})
    assert err and "current week" in out["error"]


def test_players_without_adjustments_are_told_plainly(tmp_path):
    t, star, *_ = _tools(tmp_path)
    plain = next(p for p in t.snap.my_team.roster if not p.has_edge)
    out, _ = t.call("get_edges", {"player_or_team": plain.name})
    assert out["players"][0]["adjustments"] == [] and "ESPN's number is used as is" in out["players"][0]["note"]


def test_cascade_buy_low_and_game_environment_tools(tmp_path):
    t, star, buy, sell = _tools(tmp_path)
    out, err = t.call("get_injury_cascade", {"team": "KC"})
    assert not err and out["absent"][0]["name"] == "Their RB1" and out["beneficiaries"][0]["weekly_pts"] == 3.2
    out, _ = t.call("get_injury_cascade", {"team": "XXX"})
    assert out["cascade"] is None and "No skill-position absences" in out["note"]
    out, err = t.call("get_buy_low_sell_high", {})
    assert not err and [r["name"] for r in out["buy_low"]] == [buy.name] and [r["name"] for r in out["sell_high"]] == [sell.name]
    assert "role growing" in out["note"].lower() and "NOT predictive" in out["note"]
    out, err = t.call("get_game_environment", {"game": "KC vs BUF"})
    assert not err and out["wind_mph"] == 18.0 and out["spread_for_KC"] == -2.5 and out["forecast_as_of"] and out["lines_source"] == "nflverse schedule"
    out, err = t.call("get_game_environment", {"game": "nonsense"})
    assert err
    json.dumps(t.call("get_edges", {"player_or_team": star.name})[0])


def test_system_prompt_requires_citing_adjustments():
    p = agent.system_prompt(demo_data.build_demo_snapshot())
    assert "CITE it" in p and "never claim an edge a tool did not return" in p and "AI-extracted" in p


def test_edge_ui_components_show_espn_to_adjusted_and_a_why():
    p = PlayerInfo(1, "Backup RB", "RB", "KC", "ACTIVE", "BE", ["RB"], week_proj=14.9, espn_week_proj=12.4)
    p.edge = [{"type": "cascade", "delta": 2.5, "raw": 3.4, "reason": "RB1 out -> +4 carries", "source": "nflverse", "confidence": "med", "at": 1.0}]
    assert p.has_edge and ui.edge_label(p) == "ESPN 12.4 → Adjusted 14.9"
    why = ui.edge_why(p)
    assert "<details" in why and "RB1 out" in why and "Source: nflverse" in why and "med confidence" in why and "capped from +3.4" in why
    row = ui.Brand(None).player_row(p, slot="BN")
    assert "ESPN 12.4" in row and "14.9" in row and "Edge +2.5" in row and "<details" in row
    plain = PlayerInfo(2, "No Edge", "RB", "KC", "ACTIVE", "BE", ["RB"], week_proj=8.0)
    assert ui.edge_why(plain) == "" and "ESPN" not in ui.Brand(None).player_row(plain)
    assert ui.edge_label(plain) == "ESPN 8.0"


def test_news_event_card_is_labeled_ai_extracted_and_links_the_source():
    html = ui.news_event_html({"player": "A B", "status": "out", "event_type": "injury", "summary": "He is out.", "raw_text": "A B is out.", "source_url": "https://x/y", "published_at": "2026-10-06T09:00:00Z", "beneficiaries": ["C D"]})
    assert "AI-extracted from ESPN news" in html and "Out" in html and 'href="https://x/y"' in html and "Original text" in html and "C D" in html


def test_game_environment_html_has_forecast_stamp_and_flags_wind():
    env = GameEnv("KC", "BUF", True, 3.0, 47.0, 25.0, 22.0, "odds-api", "k", "s", "outdoor", 18.0, 22.0, 40, 1.0e9, "forecast")
    h = ui.game_env_html(env)
    assert "KC favored by 3.0" in h and "Wind 18 mph" in h and "forecast" in h and "Lines: odds-api" in h
    assert "No Vegas line" in ui.game_env_html(GameEnv("KC", "BUF", True, None, None, None, None, "missing"))
