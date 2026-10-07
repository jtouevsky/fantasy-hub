from datetime import datetime

from edge import apply as eapply
from edge.engine import EngineResult, InjuryState
from edge.timing import inactives_at, timing_alerts
from edge.types import Adjustment, AdjustedProjection
from models import PlayerInfo

NOW = datetime(2026, 10, 10, 20, 0)


def P(pid, name, slot="WR", ko="2026-10-11T13:00", status="ACTIVE", proj=10.0, team="KC"):
    return PlayerInfo(pid, name, "WR", team, status, slot, [slot], week_proj=proj, game_time=ko)


def test_inactives_are_90_minutes_before_kickoff():
    assert inactives_at(datetime(2026, 10, 11, 13, 0)) == datetime(2026, 10, 11, 11, 30)
    assert inactives_at(datetime(2026, 10, 11, 16, 25)) == datetime(2026, 10, 11, 14, 55)


def test_game_time_decision_starters_are_flagged_with_recheck_time_and_bench_is_not():
    q = P(1, "Gtd Guy", status="QUESTIONABLE")
    bench = P(2, "Bench Guy", slot="BE", status="QUESTIONABLE")
    healthy = P(3, "Fine Guy")
    played = P(4, "Already Played", status="QUESTIONABLE", ko="2026-10-10T10:00")
    alerts = timing_alerts([q, bench, healthy, played], None, NOW)
    assert [a["player"] for a in alerts] == ["Gtd Guy"]
    a = alerts[0]
    assert a["inactives_at"] == datetime(2026, 10, 11, 11, 30) and "re-check before lock" in a["message"] and "11:30" in a["message"]
    assert a["hours_to_inactives"] == 15.5


def test_teammate_game_time_decision_that_changes_my_starters_role_is_flagged():
    me = P(10, "My WR2", team="CAR")
    res = EngineResult(2026, 5, 0.0)
    res.gsis_of = {10: "G10"}
    res.cascades = [{"team": "CAR", "absent": [{"gsis": "G99", "name": "Their WR1", "status": "Questionable", "p_out": 0.5, "long_term": False, "sources": []}],
                     "beneficiaries": [{"gsis": "G10", "espn_id": 10, "name": "My WR2", "pos": "WR", "weekly_pts": 2.4, "reason": "r", "confidence": "med"}]}]
    alerts = timing_alerts([me], res, NOW)
    assert len(alerts) == 1 and alerts[0]["kind"] == "teammate" and "+2.4" in alerts[0]["message"] and "Their WR1" in alerts[0]["message"]


def test_apply_keeps_espn_number_and_is_idempotent():
    p = P(1, "Adj Guy", proj=12.4)
    res = EngineResult(2026, 5, 0.0)
    res.projections = {1: AdjustedProjection(1, 2026, 5, 12.4, [Adjustment(1, 2026, 5, "cascade", 2.5, "RB1 out", "nflverse", "med")])}
    res.ros = {1: 0.8}
    res.tags = {1: [("buy low", "text")]}
    assert eapply.apply_result([p], res) == 1
    assert p.espn_week_proj == 12.4 and p.week_proj == 14.9 and p.edge_ros == 0.8 and p.tags == [["buy low", "text"]] and p.has_edge
    eapply.apply_result([p], res)                                                   # re-applying must not compound
    assert p.week_proj == 14.9 and p.espn_week_proj == 12.4
    eapply.clear([p])
    assert p.week_proj == 12.4 and not p.edge and not p.tags


def test_players_without_adjustments_keep_espn_projection():
    p = P(2, "No Data", proj=8.0)
    eapply.apply_result([p], EngineResult(2026, 5, 0.0))
    assert p.week_proj == 8.0 and not p.has_edge and p.espn_week_proj == 8.0


def test_news_from_before_the_last_game_day_is_ignored_for_this_week():
    import pandas as pd
    from edge.engine import current_week_events
    from edge.history import Hist
    games = pd.DataFrame([dict(season=2026, week=4, team="CHI", gameday="2026-10-04"), dict(season=2026, week=4, team="CAR", gameday="2026-10-04")])
    h = Hist([2026], pd.DataFrame(), games, pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
    stale = {"team": "CHI", "published_at": "2026-10-02T15:00:00Z", "status": "out"}        # 'out for Sunday' written before the Oct 4 game
    fresh = {"team": "CHI", "published_at": "2026-10-06T09:00:00Z", "status": "out"}
    unknown_team = {"team": "XXX", "published_at": "2026-09-01T00:00:00Z"}
    assert current_week_events(h, 2026, 5, [stale, fresh, unknown_team]) == [fresh, unknown_team]
