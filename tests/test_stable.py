import numpy as np
import pandas as pd
import pytest

import optimizer
from edge import stable as sb
from models import PlayerInfo
from valuation import blended_ppg

PARAMS = {"kv": 8.0, "ktd": 10.0, "window": 8, "dep_penalty": -2.0, "quant": {}}


def games(n, vol, td, xvol, xtd, targets, carries=0, share=0.2, texp=None):
    """n identical games; td is points from TDs, xtd the points an average player would have scored from this opportunity."""
    r = dict(pts=vol + td, vol_pts=vol, td_pts=td, xvol_pts=xvol, xtd_pts=xtd, targets=targets, carries=carries, target_share=share,
             passing_tds=0.0, rushing_tds=0.0, receiving_tds=td / 6, pass_touchdown_exp=0.0, rush_touchdown_exp=0.0, rec_touchdown_exp=xtd / 6)
    return pd.DataFrame([r] * n)


def test_td_fluke_ranks_below_volume_at_the_same_points_per_game():
    """The brief's sanity check: 3 catches + a TD every week vs 8 catches for 90 yards with no TD, same points per game."""
    fluke = games(4, vol=8.6, td=6.0, xvol=8.0, xtd=0.9, targets=4.0, share=0.14)          # 14.6 ppg; opportunity says ~8.9
    volume = games(4, vol=14.0, td=0.0, xvol=13.5, xtd=1.6, targets=11.0, share=0.30)      # 14.0 ppg; opportunity says ~15.1
    a, b = sb.player_stable(fluke, "WR", PARAMS), sb.player_stable(volume, "WR", PARAMS)
    assert a["raw_ppg"] > b["raw_ppg"]                       # raw points per game would rank the fluke first ...
    assert a["ppg"] < b["ppg"]                               # ... stability-weighted value ranks the volume receiver first
    assert a["dependent"] and not b["dependent"] and b["volume_backed"]
    assert a["td_share"] > 0.4 and b["td_share"] == 0


def test_tds_regress_harder_than_nothing_and_volume_is_kept():
    g = games(8, vol=10.0, td=6.0, xvol=10.0, xtd=1.0, targets=8.0)
    s = sb.player_stable(g, "WR", {**PARAMS, "dep_penalty": 0.0})
    assert 10.0 + 1.0 < s["ppg"] < 16.0                      # between "all expected" and "all actual"
    assert s["ppg"] == pytest.approx(10.0 + (8 * 6.0 + 10 * 1.0) / 18, abs=0.01)
    assert sb.estimate(10, 6, 10, 1, 0, 8, 10) == pytest.approx(11.0)       # no games: pure expectation


def test_not_enough_games_gives_no_profile():
    assert sb.player_stable(games(2, 8, 2, 8, 1, 5), "WR", PARAMS) is None


def test_floor_median_ceiling_modes_change_the_lineup_value():
    p = PlayerInfo(1, "A", "WR", "KC", "ACTIVE", "WR", ["WR"], week_proj=14.0, stable={"r": [0.4, 0.9, 1.5]})
    try:
        vals = {m: optimizer.dist_value(p, m) for m in ("Median", "Safe", "Upside", "Mean")}
    finally:
        optimizer.set_risk_mode("Median")
    assert vals["Safe"] < vals["Median"] < vals["Upside"] and vals["Mean"] == 14.0
    assert vals["Median"] == pytest.approx(14.0 * 0.9)
    plain = PlayerInfo(2, "B", "WR", "KC", "ACTIVE", "WR", ["WR"], week_proj=10.0)
    assert optimizer.dist_value(plain, "Safe") == 10.0       # no distribution data: the plain projection


def test_a_safe_lineup_prefers_the_higher_floor_player():
    steady = PlayerInfo(1, "Steady", "WR", "KC", "ACTIVE", "BE", ["WR", "BE"], week_proj=12.0, stable={"r": [0.7, 0.95, 1.2]})
    boom = PlayerInfo(2, "Boom", "WR", "KC", "ACTIVE", "BE", ["WR", "BE"], week_proj=12.5, stable={"r": [0.25, 0.8, 1.9]})
    try:
        optimizer.set_risk_mode("Safe")
        safe = optimizer.best_lineup([steady, boom], {"WR": 1})
        optimizer.set_risk_mode("Upside")
        up = optimizer.best_lineup([steady, boom], {"WR": 1})
    finally:
        optimizer.set_risk_mode("Median")
    assert safe[0].name == "Steady" and up[0].name == "Boom"


def test_valuation_uses_stable_points_instead_of_raw_when_present():
    raw = PlayerInfo(1, "A", "WR", "KC", "ACTIVE", "WR", ["WR"], total_points=14.6 * 4, games_played=4, season_proj_ppg=10.0)
    st = PlayerInfo(2, "A", "WR", "KC", "ACTIVE", "WR", ["WR"], total_points=14.6 * 4, games_played=4, season_proj_ppg=10.0, stable={"ppg": 9.0, "g": 4})
    assert blended_ppg(st) < blended_ppg(raw)


def test_tags_carry_the_numbers():
    fluke = sb.player_stable(games(8, 8.6, 6.0, 8.0, 0.9, 4.0), "WR", PARAMS)
    p = PlayerInfo(1, "F", "WR", "KC", "ACTIVE", "WR", ["WR"], stable=fluke)
    (tag, why), = sb.tags_for(p)
    assert tag == "td-dependent" and "touchdowns" in why and "touches+targets" in why
    vol = PlayerInfo(2, "V", "WR", "KC", "ACTIVE", "WR", ["WR"], stable=sb.player_stable(games(8, 14, 0, 13.5, 1.6, 11.0, share=0.3), "WR", PARAMS))
    assert sb.tags_for(vol)[0][0] == "volume-backed"
    sb.apply_to_players([p], {1: fluke})
    assert any(t[0] == "td-dependent" for t in p.tags)
