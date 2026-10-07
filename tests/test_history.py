import league_client as lc


def test_points_from_raw_applies_league_scoring():
    items = [{"statId": 53, "points": 1.0}, {"statId": 42, "points": 0.1}, {"statId": 43, "points": 6.0}, {"statId": 99, "points": 5.0}]
    raw = {"53": 8, "42": 95, "43": 1}                      # 8 catches, 95 yds, 1 TD (stat 99 absent)
    assert lc.points_from_raw(raw, items) == 23.5


def test_history_uses_espn_applied_total_and_falls_back_to_computed():
    card = {"players": [{"player": {"stats": [
        {"seasonId": 2026, "scoringPeriodId": 2, "statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": 18.14, "stats": {"53": 9}},
        {"seasonId": 2026, "scoringPeriodId": 3, "statSourceId": 0, "statSplitTypeId": 1, "stats": {"53": 5, "42": 50}},
        {"seasonId": 2026, "scoringPeriodId": 0, "statSourceId": 0, "statSplitTypeId": 0, "appliedTotal": 99.0},     # season total: ignored
        {"seasonId": 2026, "scoringPeriodId": 5, "statSourceId": 1, "statSplitTypeId": 1, "appliedTotal": 12.0},     # projection: ignored
        {"seasonId": 2025, "scoringPeriodId": 18, "statSourceId": 0, "statSplitTypeId": 1, "appliedTotal": 13.5, "stats": {}},
    ]}}]}
    items = [{"statId": 53, "points": 1.0}, {"statId": 42, "points": 0.1}]
    h = lc._history_from_card(card, items)
    assert [(r["season"], r["week"], r["points"], r["source"]) for r in h] == [
        (2025, 18, 13.5, "espn"), (2026, 2, 18.1, "espn"), (2026, 3, 10.0, "computed")]
