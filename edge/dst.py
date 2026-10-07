"""D/ST matchup model for streaming.

D/ST points (ESPN default D/ST scoring: sack 1, INT 2, fumble recovery 2, defensive/return TD 6, safety 2, blocked kick 2, points-allowed bands)
are computed from nflverse team stats and regressed on the opponent's matchup: its Vegas implied total, how often it turns the ball over,
how often it gives up sacks (trailing 4 games, no leakage), and wind. The fit is validated out of sample (fit older seasons, score the
newest) against "this defense's own trailing mean". Everything here is labelled a *matchup estimate*, not a projection from ESPN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.history import Hist, _nfl, tkey
from edge.ids import norm_team

PA_BANDS = [(0, 5), (6, 4), (13, 3), (17, 1), (27, 0), (34, -1), (45, -3), (999, -5)]
LEAGUE_AVG_IMPLIED = 22.5
FEATURES = ["opp_imp", "opp_to", "opp_sack", "wind15"]


def pa_points(pa: float) -> float:
    for cap, pts in PA_BANDS:
        if pa <= cap:
            return float(pts)
    return -5.0


def team_games(seasons: list[int], h: Hist) -> pd.DataFrame:
    """One row per defense-game: D/ST fantasy points + the opponent's offensive tendencies as of before that game."""
    nfl = _nfl()
    t = nfl.load_team_stats(seasons).to_pandas()
    t = t[t.season_type == "REG"].copy()
    t["team"] = t.team.map(norm_team)
    t["opp"] = t.opponent_team.map(norm_team)
    sc = nfl.load_schedules(seasons).to_pandas()
    sc = sc[sc.game_type == "REG"]
    pts = pd.concat([sc[["season", "week", "home_team", "away_team", "away_score"]].rename(columns={"home_team": "team", "away_team": "opp", "away_score": "pa"}),
                     sc[["season", "week", "away_team", "home_team", "home_score"]].rename(columns={"away_team": "team", "home_team": "opp", "home_score": "pa"})])
    pts["team"], pts["opp"] = pts.team.map(norm_team), pts.opp.map(norm_team)
    d = t.merge(pts[["season", "week", "team", "pa"]], on=["season", "week", "team"], how="left")
    td = d.get("def_tds", 0) + d.get("fumble_recovery_tds", 0)
    d["dst_pts"] = (d.def_sacks.fillna(0) + 2 * d.def_interceptions.fillna(0) + 2 * d.fumble_recovery_opp.fillna(0) + 6 * td.fillna(0) + 2 * d.def_safeties.fillna(0)
                    + 2 * (d.def_punt_blocks.fillna(0) + d.def_fg_blocks.fillna(0) + d.def_pat_blocks.fillna(0)) + d.pa.map(lambda x: pa_points(x) if pd.notna(x) else np.nan))
    # opponent offense tendencies, trailing 4 games (shifted so the game itself is excluded)
    off = t.assign(turnovers=t.passing_interceptions.fillna(0) + t.sack_fumbles_lost.fillna(0) + t.rushing_fumbles_lost.fillna(0) + t.receiving_fumbles_lost.fillna(0))
    off = off.sort_values(["team", "season", "week"])
    for col, new in (("turnovers", "to_tr"), ("sacks_suffered", "sack_tr")):
        off[new] = off.groupby("team")[col].transform(lambda s: s.shift(1).rolling(4, min_periods=2).mean())
    d = d.merge(off[["season", "week", "team", "to_tr", "sack_tr"]].rename(columns={"team": "opp", "to_tr": "opp_to", "sack_tr": "opp_sack"}), on=["season", "week", "opp"], how="left")
    g = h.games[["season", "week", "team", "implied", "opp_implied", "wind"]].copy()
    d = d.merge(g.rename(columns={"opp_implied": "opp_imp"})[["season", "week", "team", "opp_imp", "wind"]], on=["season", "week", "team"], how="left")
    d["wind15"] = (d.wind.fillna(0) >= 15).astype(float)
    d["t"] = tkey(d.season, d.week)
    d = d.sort_values(["team", "t"])
    d["own_mean"] = d.groupby("team").dst_pts.transform(lambda s: s.shift(1).rolling(6, min_periods=3).mean())
    return d.dropna(subset=["dst_pts", "opp_imp", "opp_to", "opp_sack", "own_mean"])


def fit(d: pd.DataFrame) -> dict:
    X = np.column_stack([np.ones(len(d))] + [(d[f] - d[f].mean()).values for f in FEATURES])
    beta = np.linalg.lstsq(X.T @ X + 5.0 * np.diag([0] + [1] * len(FEATURES)), X.T @ d.dst_pts.values, rcond=None)[0]
    return {"intercept": float(beta[0]), "means": {f: float(d[f].mean()) for f in FEATURES}, "coef": dict(zip(FEATURES, map(float, beta[1:]))), "n": int(len(d))}


def predict(model: dict, row: dict) -> float:
    return model["intercept"] + sum(model["coef"][f] * (row[f] - model["means"][f]) for f in FEATURES)


def validate(h: Hist, seasons: list[int]) -> dict:
    d = team_games(seasons, h)
    last = max(seasons)
    tr, te = d[d.season < last], d[d.season == last]
    m = fit(tr)
    pred = np.array([predict(m, r) for r in te[FEATURES].to_dict("records")])
    shrunk = 0.5 * pred + 0.5 * te.own_mean.values
    mae = lambda x: float(np.mean(np.abs(te.dst_pts.values - x)))
    return {"n_test": int(len(te)), "coef": m["coef"], "mae_matchup": mae(pred), "mae_own_mean": mae(te.own_mean.values), "mae_blend": mae(shrunk),
            "corr_matchup": float(np.corrcoef(pred, te.dst_pts)[0, 1]), "corr_own_mean": float(np.corrcoef(te.own_mean, te.dst_pts)[0, 1])}


def live_estimates(h: Hist, seasons: list[int], season: int, week: int, model: dict | None = None) -> dict[str, dict]:
    """{team: {est, opp, opp_imp, opp_to, opp_sack, wind, reasons}} for the games in `week` (works for next week too if the schedule has lines)."""
    nfl = _nfl()
    d = team_games(seasons, h)
    model = model or fit(d[d.t < tkey(season, week)])
    t = nfl.load_team_stats(seasons).to_pandas()
    t = t[(t.season_type == "REG")].copy()
    t["team"] = t.team.map(norm_team)
    t["t"] = tkey(t.season, t.week)
    t = t[t.t < tkey(season, week)].sort_values(["team", "t"])
    t["turnovers"] = t.passing_interceptions.fillna(0) + t.sack_fumbles_lost.fillna(0) + t.rushing_fumbles_lost.fillna(0) + t.receiving_fumbles_lost.fillna(0)
    tr = t.groupby("team").tail(4).groupby("team").agg(to=("turnovers", "mean"), sack=("sacks_suffered", "mean"))
    g = h.games[(h.games.season == season) & (h.games.week == week)]
    out = {}
    for r in g.itertuples():
        if r.opp not in tr.index or pd.isna(r.opp_implied):
            continue
        wind = float(r.wind) if pd.notna(r.wind) and str(r.roof) in ("outdoors", "open", "nan", "None") else 0.0
        row = {"opp_imp": float(r.opp_implied), "opp_to": float(tr.loc[r.opp, "to"]), "opp_sack": float(tr.loc[r.opp, "sack"]), "wind15": float(wind >= 15)}
        est = predict(model, row)
        reasons = []
        if row["opp_imp"] <= 20.5:
            reasons.append(f"{r.opp} is a low-scoring offense this week (implied {row['opp_imp']:.1f} pts)")
        elif row["opp_imp"] >= 25.0:
            reasons.append(f"{r.opp} is expected to score a lot (implied {row['opp_imp']:.1f} pts)")
        if row["opp_to"] >= 1.6:
            reasons.append(f"{r.opp} turns it over {row['opp_to']:.1f}x/game lately")
        if row["opp_sack"] >= 3.0:
            reasons.append(f"{r.opp} allows {row['opp_sack']:.1f} sacks/game lately")
        if row["wind15"]:
            reasons.append(f"wind {wind:.0f} mph")
        out[r.team] = {"est": float(est), "opp": r.opp, **row, "wind": wind, "reasons": reasons}
    return out


def main() -> None:
    h = Hist.load([2023, 2024, 2025])
    v = validate(h, [2023, 2024, 2025])
    print(v)


if __name__ == "__main__":
    main()
