from datetime import datetime, timezone

import pytest

import db
from edge import forecast, odds, stadiums
from edge.settings import EdgeSettings

NAMES = {"Kansas City Chiefs": "KC", "Buffalo Bills": "BUF", "Washington Commanders": "WSH"}


def _ev(home="Kansas City Chiefs", away="Buffalo Bills", pts=(-3.5, -3.0, -3.5), totals=(47.5, 48.0, 47.5)):
    return {"home_team": home, "away_team": away, "commence_time": "2026-10-11T17:00:00Z", "bookmakers": [
        {"key": f"b{i}", "markets": [{"key": "spreads", "outcomes": [{"name": home, "price": -110, "point": p}, {"name": away, "price": -110, "point": -p}]},
                                     {"key": "totals", "outcomes": [{"name": "Over", "point": t, "price": -110}, {"name": "Under", "point": t, "price": -110}]}]}
        for i, (p, t) in enumerate(zip(pts, totals))]}


def test_parse_events_uses_median_and_nflverse_sign_convention():
    got = odds.parse_events([_ev(), {"home_team": "Mystery FC", "away_team": "Buffalo Bills", "bookmakers": []}], NAMES)
    assert len(got) == 1 and got[0]["home"] == "KC" and got[0]["away"] == "BUF"
    assert got[0]["spread_home_fav"] == 3.5          # home -3.5 => home favored by 3.5 => positive (nflverse spread_line convention)
    assert got[0]["total"] == 47.5 and got[0]["n_books"] == 3


def test_odds_without_key_returns_none_and_never_calls_api(tmp_path):
    def boom():
        raise AssertionError("must not call the API without a key")
    assert odds.get_odds(EdgeSettings(odds_api_key=""), NAMES, str(tmp_path / "o.db"), fetch=boom) is None


def test_odds_are_cached_to_protect_the_free_quota(tmp_path):
    calls = []
    p = str(tmp_path / "o.db")
    s = EdgeSettings(odds_api_key="k", odds_ttl_hours=12)
    f = lambda: calls.append(1) or [_ev()]
    a = odds.get_odds(s, NAMES, p, fetch=f)
    b = odds.get_odds(s, NAMES, p, fetch=f)
    assert a == b and len(calls) == 1                # second call within the TTL costs zero API credits


def test_odds_failure_falls_back_to_stale_cache_or_none(tmp_path):
    p = str(tmp_path / "o.db")
    s = EdgeSettings(odds_api_key="k", odds_ttl_hours=0.0)
    def fail():
        raise RuntimeError("network")
    assert odds.get_odds(s, NAMES, p, fetch=fail) is None
    db.cache_set(odds.CACHE_KEY, [{"home": "KC"}], p)
    assert odds.get_odds(s, NAMES, p, fetch=fail) == [{"home": "KC"}]


def test_stadium_table_covers_all_teams_and_flags_domes():
    assert len(stadiums.STADIUMS) == 32
    assert stadiums.STADIUMS["DET"][3] == "dome" and stadiums.STADIUMS["DAL"][3] == "retractable" and stadiums.STADIUMS["GB"][3] == "outdoor"
    assert stadiums.locate("JAX", "Tottenham Hotspur Stadium")[3] == "Tottenham Hotspur Stadium"     # neutral site wins
    assert stadiums.locate("JAX")[3] == "EverBank Stadium"


def test_kickoff_conversion_and_forecast_window():
    ko = forecast.kickoff_utc("2026-10-11", "13:00")
    assert ko == datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)         # 1pm ET (EDT) = 17:00Z
    times = [f"2026-10-11T{h:02d}:00" for h in range(14, 24)]
    payload = {"hourly": {"time": times, "temperature_2m": [50] * 10, "wind_speed_10m": [10, 12, 18, 20, 22, 8, 8, 8, 8, 8],
                          "wind_gusts_10m": [15] * 10, "precipitation_probability": [0, 0, 60, 80, 20, 0, 0, 0, 0, 0], "precipitation": [0, 0, 1, 2, 0, 0, 0, 0, 0, 0]}}
    got = forecast.pick_hours(payload, ko)
    assert got["wind_mph"] == pytest.approx((12 + 18 + 20) / 3 + 0, abs=3) and got["precip_prob"] == 80


def test_domes_skip_the_weather_api_entirely(tmp_path):
    got = forecast.game_forecast("DET", None, "2026-10-11", "13:00", EdgeSettings(), str(tmp_path / "w.db"), fetch=lambda: (_ for _ in ()).throw(AssertionError("no call")))
    assert got["indoor"] is True and got["roof"] == "dome"


def test_forecast_is_cached_and_carries_a_timestamp(tmp_path):
    calls, p = [], str(tmp_path / "w.db")
    times = [f"2026-10-11T{h:02d}:00" for h in range(16, 22)]
    payload = {"hourly": {"time": times, "temperature_2m": [40] * 6, "wind_speed_10m": [17] * 6, "wind_gusts_10m": [25] * 6, "precipitation_probability": [10] * 6, "precipitation": [0] * 6}}
    f = lambda: calls.append(1) or payload
    a = forecast.game_forecast("GB", None, "2026-10-11", "13:00", EdgeSettings(), p, fetch=f)
    b = forecast.game_forecast("GB", None, "2026-10-11", "13:00", EdgeSettings(), p, fetch=f)
    assert a["wind_mph"] == 17 and a["fetched_at"] == b["fetched_at"] and len(calls) == 1
