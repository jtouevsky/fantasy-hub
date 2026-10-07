"""Deterministic half of the agent scenarios: the shared move engine behind the assistant gives the right answer."""
import pytest

from tests.agent_scenarios import scenarios as sc


@pytest.mark.parametrize("make", sc.ALL, ids=lambda f: f.__name__)
def test_find_moves_scenario(make):
    s = make()
    res, err = s.tools.call("find_moves", {})
    assert not err, res
    s.check_moves(res)


def test_agent_cannot_bypass_rules_with_evaluate_move():
    s = sc.two_qbs_never_a_third()
    res, err = s.tools.call("evaluate_move", {"add": "Kyler Murray", "drop": s.tools.snap.my_team.roster[3].name})
    assert not err and res["allowed"] is False and res["blocked_because"]


def test_player_rows_never_report_zero_value_or_irrelevant_byes():
    s = sc.no_good_moves()
    row = s.tools._player_row(s.tools.snap.my_team.roster[0])
    assert "rest_of_season_value" not in row and "bye_week" not in row
