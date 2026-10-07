import copy
import json
from types import SimpleNamespace as NS

import pytest

import agent
import db
import demo_data
from valuation import ValueModel


def _tools(tmp_path):
    snap = demo_data.build_demo_snapshot()
    fas = demo_data.build_demo_free_agents()
    model = ValueModel(snap, fas)
    fetch = lambda pos, n: [p for p in fas if pos in (None, p.position)]
    news = lambda pid, n: [{"headline": "H", "story": "S", "published": "2026-10-06T00:00:00Z"}]
    return agent.AgentTools(snap, model, fetch, news, db_path=str(tmp_path / "a.db"))


class FakeClaude:
    """Scripted responses: list of (stop_reason, [blocks])."""
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(copy.deepcopy(kw))      # the real SDK serializes at call time
        stop, blocks = self.script.pop(0)
        return NS(stop_reason=stop, content=blocks)


def tu(i, name, **inp):
    return NS(type="tool_use", id=f"t{i}", name=name, input=inp)


def tx(text):
    return NS(type="text", text=text)


def test_every_tool_runs_on_demo_data(tmp_path):
    t = _tools(tmp_path)
    me = t.snap.my_team
    mine, theirs = me.roster[0], t.snap.find_team("Kaden").roster[0]
    calls = {
        "get_league_overview": {}, "get_my_roster": {}, "get_team_roster": {"team_name_or_owner": "Kaden"},
        "get_free_agents": {"position": "WR", "limit": 3}, "optimize_lineup": {}, "find_moves": {},
        "evaluate_trade": {"give": [mine.name], "get": [theirs.name]},
        "find_trades": {"request": "a receiver at about 55/45", "target_team": "Kaden", "offering": [mine.name], "target_split": 55},
        "get_player_news": {"player": mine.name},
        "evaluate_move": {"add": t.fetch_free_agents("WR", 30)[0].name},
        "get_strategy": {}, "get_manager_profile": {"manager": "Kaden"},
        "draft_trade_pitch": {"give": [mine.name], "get": [theirs.name], "team_name_or_owner": "Kaden"},
        "log_negotiation": {"manager": "Kaden", "offer": {"give": [mine.name], "get": [theirs.name]}, "response": "rejected", "note": "test"},
        "log_recommendation": {"kind": "trade", "summary": "x"},
    }
    edge_tools = {"get_edges": {"player_or_team": mine.name}, "get_injury_cascade": {"team": "KC"}, "get_buy_low_sell_high": {}, "get_game_environment": {"game": "KC"}}
    assert set(calls) | set(edge_tools) == agent.TOOL_NAMES
    for name, args in calls.items():
        out, err = t.call(name, args)
        assert not err, (name, out)
        json.dumps(out)                                  # results must be JSON-serializable
    for name, args in edge_tools.items():                # demo mode has no edge engine: tools must say so plainly instead of inventing data
        out, err = t.call(name, args)
        assert err and "edge engine isn't running" in out["error"], (name, out)


def test_team_lookup_by_owner_first_name_and_errors_are_returned_not_raised(tmp_path):
    t = _tools(tmp_path)
    out, err = t.call("get_team_roster", {"team_name_or_owner": "kaden"})
    assert not err and out["owner"].startswith("Kaden")
    out, err = t.call("get_team_roster", {"team_name_or_owner": "Zed"})
    assert err and "No team matches" in out["error"]
    out, err = t.call("find_trades", {"target_team": "Kaden", "offering": ["Not A Player"]})
    assert err
    out, err = t.call("drop_database", {})
    assert err


def test_agent_loop_uses_tools_then_answers_and_logs(tmp_path):
    t = _tools(tmp_path)
    mine = t.snap.my_team.roster[0].name
    client = FakeClaude([
        ("tool_use", [tx("Let me look."), tu(1, "find_trades", target_team="Kaden", offering=[mine], target_split=60)]),
        ("tool_use", [tu(2, "get_team_roster", team_name_or_owner="Nobody")]),             # an error the model recovers from
        ("end_turn", [tx("Try this trade. Do this in the ESPN app: propose it.")]),
    ])
    res = agent.run_turn(client, "claude-sonnet-5-5", t, [], "best trade with Kaden?")
    assert "Do this in the ESPN app" in res.text
    assert [x["tool"] for x in res.tool_trace] == ["find_trades", "get_team_roster"]
    assert res.tool_trace[1]["error"] is True
    # tool results were fed back as tool_result blocks with matching ids
    second_call_msgs = client.calls[1]["messages"]
    assert second_call_msgs[-1]["content"][0]["type"] == "tool_result" and second_call_msgs[-1]["content"][0]["tool_use_id"] == "t1"
    # safety-net log entry exists (agent never called log_recommendation itself)
    rows = db.list_recommendations(path=t.db_path)
    assert len(rows) == 1 and rows[0]["kind"] == "trade" and rows[0]["source"] == "agent"
    # history is JSON-serializable and can seed the next turn
    json.dumps(res.history)
    assert client.calls[0]["tools"] == agent.TOOLS and "NEVER state a stat" in client.calls[0]["system"][0]["text"]


def test_explicit_log_call_prevents_duplicate_auto_log(tmp_path):
    t = _tools(tmp_path)
    client = FakeClaude([
        ("tool_use", [tu(1, "optimize_lineup")]),
        ("tool_use", [tu(2, "log_recommendation", kind="lineup", summary="Start X")]),
        ("end_turn", [tx("Done. Do this in the ESPN app: start X.")]),
    ])
    agent.run_turn(client, "m", t, [], "set my lineup")
    assert len(db.list_recommendations(path=t.db_path)) == 1


def test_tool_loop_is_bounded(tmp_path):
    t = _tools(tmp_path)
    client = FakeClaude([("tool_use", [tu(i, "get_my_roster")]) for i in range(agent.MAX_TOOL_ROUNDS + 2)])
    res = agent.run_turn(client, "m", t, [], "loop forever")
    assert "tool-call limit" in res.text and len(client.calls) == agent.MAX_TOOL_ROUNDS


def test_chat_backend_defaults_to_subscription_and_ignores_placeholder_key(monkeypatch):
    import config
    monkeypatch.delenv("CHAT_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_anthropic_api_key_here")
    cfg = config.load_config()
    assert cfg.chat_backend == "subscription" and cfg.anthropic_api_key == ""
    monkeypatch.setenv("CHAT_BACKEND", "api")
    assert config.load_config().chat_backend == "api"


def test_answer_written_beside_the_log_call_is_not_lost(tmp_path):
    t = _tools(tmp_path)
    client = FakeClaude([
        ("tool_use", [tx("Start Sutton: ESPN 10.2 -> adjusted 12.0 (opportunity edge, low confidence). Do this in the ESPN app: start him."), tu(1, "log_recommendation", kind="lineup", summary="Start Sutton")]),
        ("end_turn", [tx("I've logged the recommendation.")]),
    ])
    res = agent.run_turn(client, "m", t, [], "who do I start?")
    assert "ESPN 10.2 -> adjusted 12.0" in res.text and "I've logged" not in res.text
    assert agent._final_answer(["Real answer here that is long enough to matter.", "Logged it."]) == "Real answer here that is long enough to matter."
    assert agent._final_answer(["Only message, and it mentions logged but is the whole answer."]) == "Only message, and it mentions logged but is the whole answer."
