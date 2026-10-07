"""Backtest of the market-value proxy idea: does the model-vs-market gap predict rest-of-season points?

Offline only. Market = FantasyPros expert-consensus ranks from nflverse's `load_ff_rankings` snapshot nearest the season start
(the only in-season-relevant snapshot published; later pages are end-of-season). It is a stale-by-design proxy for how managers
anchor on preseason reputation. Model = games-played blend of a player's actual ppg through week 4 with a prior built from last
season's ppg (no ECR in it, so the two are independent). Decision week 5. Outcome = actual points weeks 5..17.
Tune on 2024, validate on 2025. Usage: python -m tools.trade_backtest
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.history import Hist, _nfl

K = 4
DECISION_WEEK = 5
POS = ["QB", "RB", "WR", "TE"]


def _ecr(nfl, season: int) -> pd.DataFrame:
    d = nfl.load_ff_rankings("all").to_pandas()
    d["date"] = pd.to_datetime(d.scrape_date)
    d = d[(d.page_type.isin(["best-qb", "best-rb", "best-wr", "best-te"])) & (d.date >= f"{season}-08-15") & (d.date <= f"{season}-09-20")]
    d = d[d.date == d.date.min()]
    ids = nfl.load_ff_playerids().to_pandas()[["fantasypros_id", "gsis_id"]].dropna().drop_duplicates("fantasypros_id")
    ids["fantasypros_id"] = ids.fantasypros_id.astype(float).astype(int)
    d = d.assign(id=pd.to_numeric(d.id, errors="coerce")).dropna(subset=["id"]).assign(id=lambda x: x.id.astype(int))
    d = d.merge(ids, left_on="id", right_on="fantasypros_id", how="inner")
    return d.rename(columns={"pos": "ecr_pos"})[["gsis_id", "ecr_pos", "ecr"]].drop_duplicates("gsis_id")


def frame(h: Hist, nfl, season: int) -> pd.DataFrame:
    w = h.weekly
    prev = w[w.season == season - 1].groupby("gsis").pts.agg(["mean", "count"]).rename(columns={"mean": "prev_ppg", "count": "prev_g"})
    cur = w[(w.season == season) & (w.week < DECISION_WEEK)].groupby("gsis").pts.agg(["sum", "count"]).rename(columns={"sum": "cur_sum", "count": "cur_g"})
    ros = w[(w.season == season) & (w.week >= DECISION_WEEK) & (w.week <= 17)].groupby("gsis").pts.sum().rename("ros")
    pos = w.drop_duplicates("gsis", keep="last").set_index("gsis").pos
    e = _ecr(nfl, season).set_index("gsis_id")
    df = e.join(prev).join(cur).join(ros).join(pos).fillna({"cur_sum": 0, "cur_g": 0, "ros": 0})
    df = df[df.pos.isin(POS)].dropna(subset=["prev_ppg"])
    pm = df.groupby("pos").prev_ppg.transform("mean")
    prior = 0.8 * df.prev_ppg + 0.2 * pm
    df["model_ppg"] = (df.cur_sum + K * prior) / (df.cur_g + K)
    # position ranks among ranked players
    df["model_rank"] = df.groupby("pos").model_ppg.rank(ascending=False)
    df["ecr_rank"] = df.groupby("pos").ecr.rank()
    df["gap"] = df.ecr_rank - df.model_rank          # >0: model likes him more than the market does
    df["season"] = season
    return df[df.ecr_rank <= {"QB": 24, "RB": 48, "WR": 60, "TE": 20}.get(df.pos.iloc[0], 40)] if False else df


def evaluate(df: pd.DataFrame, fit: tuple | None = None) -> dict:
    d = df[df.apply(lambda r: r.ecr_rank <= {"QB": 20, "RB": 40, "WR": 50, "TE": 16}[r.pos], axis=1)].copy()
    # market expectation: mean ROS points at that positional ECR rank (smooth poly per position, fit on `fit` data or itself)
    if fit is None:
        fit = tuple({p: np.polyfit(g.ecr_rank, g.ros, 2) for p, g in d.groupby("pos")}.items())
    coefs = dict(fit)
    d["mkt_exp"] = d.apply(lambda r: np.polyval(coefs[r.pos], r.ecr_rank), axis=1)
    d["resid"] = d.ros - d.mkt_exp
    out = {"n": len(d), "coefs": fit, "corr_gap_resid": float(np.corrcoef(d.gap, d.resid)[0, 1])}
    slope = np.polyfit(d.gap, d.resid, 1)
    out["resid_pts_per_rank_of_gap"] = float(slope[0])
    q = d.gap.quantile([0.2, 0.8]).values
    out["top20_gap_resid"] = float(d[d.gap >= q[1]].resid.mean()); out["bottom20_gap_resid"] = float(d[d.gap <= q[0]].resid.mean())
    out["top20_n"] = int((d.gap >= q[1]).sum())
    # hit rate: top-quintile gap players beat their market expectation
    out["top20_hit"] = float((d[d.gap >= q[1]].resid > 0).mean())
    out["bottom20_hit"] = float((d[d.gap <= q[0]].resid < 0).mean())
    return out


def main() -> None:
    nfl = _nfl()
    h = Hist.load([2023, 2024, 2025])
    f24, f25 = frame(h, nfl, 2024), frame(h, nfl, 2025)
    r24 = evaluate(f24)
    r25 = evaluate(f25, fit=r24["coefs"])
    for name, r in (("2024 (tune)", r24), ("2025 (validate, 2024 market curve)", r25)):
        print(f"\n{name}: n={r['n']}  corr(gap, ROS surprise)={r['corr_gap_resid']:+.2f}  pts per rank of gap={r['resid_pts_per_rank_of_gap']:+.2f}")
        print(f"  top-20% gap (model likes more): ROS vs market expectation {r['top20_gap_resid']:+.1f} pts (n={r['top20_n']}, beat market {r['top20_hit']:.0%})")
        print(f"  bottom-20% gap (model likes less): {r['bottom20_gap_resid']:+.1f} pts (underperformed market {r['bottom20_hit']:.0%})")


if __name__ == "__main__":
    main()
