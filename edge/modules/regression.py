"""Module 5: opportunity vs. production (regression signals) and role trends.

xFP (expected fantasy points from nflverse ff_opportunity) measures the volume/quality of a player's opportunities. Over
~4 games, players whose actual points trail xFP tend to bounce back ("buy low") and TD-fueled overproducers tend to fade
("sell high"). Rising snap share / target share signals a growing role. Coefficients are estimated on 2024 residuals.

Tags use fixed thresholds and are validated separately in the backtest (what actually happened next).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.modules.base import Module, empty_pred, ols_through_origin

POS = ["QB", "RB", "WR", "TE"]
BUY_LOW_GAP = 3.0        # xFP exceeds actual by >= this many pts/game over the last 4 games
SELL_HIGH_GAP = -3.0
ROLE_GROWING = 0.08      # snap-share gain: last 2 games vs. the 2 before


def build_signals(h) -> pd.DataFrame:
    """Per player-game: gap4 (mean xFP - actual over the previous 4 games with xFP) and dsnap (snap share trend). Pre-game only."""
    c = getattr(h, "_reg_signals", None)
    if c is not None:
        return c
    x = h.xfp.sort_values(["gsis", "t"]).copy()
    x["gap"] = x.xfp - x.xfp_actual
    x["gap4"] = x.groupby("gsis")["gap"].transform(lambda s: s.shift(1).rolling(4, min_periods=3).mean())
    x["xfp4"] = x.groupby("gsis")["xfp"].transform(lambda s: s.shift(1).rolling(4, min_periods=3).mean())
    s = h.snaps.sort_values(["gsis", "t"]).copy()
    s = s[s.offense_pct > 0]
    s["last2"] = s.groupby("gsis")["offense_pct"].transform(lambda v: v.shift(1).rolling(2, min_periods=2).mean())
    s["prior2"] = s.groupby("gsis")["offense_pct"].transform(lambda v: v.shift(3).rolling(2, min_periods=2).mean())
    s["dsnap"] = s.last2 - s.prior2
    out = x[["gsis", "t", "gap4", "xfp4"]].merge(s[["gsis", "t", "dsnap", "last2"]], on=["gsis", "t"], how="outer")
    h._reg_signals = out
    return out


def signals_asof(h, gsis_list, tw: int) -> pd.DataFrame:
    """Signals for UPCOMING games (time tw), from games strictly before tw. Same definitions as build_signals (4-game xFP gap
    needing >= 3 games; snap-share last 2 games vs the 2 before) so live numbers match what was backtested."""
    x = h.xfp[(h.xfp.t < tw) & h.xfp.gsis.isin(list(gsis_list))].sort_values(["gsis", "t"])
    x = x.assign(gap=x.xfp - x.xfp_actual)
    g4 = x.groupby("gsis").tail(4).groupby("gsis").agg(gap4=("gap", "mean"), n=("gap", "size"), xfp4=("xfp", "mean"))
    g4 = g4[g4.n >= 3].drop(columns="n")
    s = h.snaps[(h.snaps.t < tw) & (h.snaps.offense_pct > 0) & h.snaps.gsis.isin(list(gsis_list))].sort_values(["gsis", "t"])
    def trend(v):
        v = v.to_numpy()
        return (v[-2:].mean() - v[-4:-2].mean()) if len(v) >= 4 else np.nan
    ds = s.groupby("gsis")["offense_pct"].apply(trend).rename("dsnap")
    return pd.concat([g4, ds], axis=1).reset_index().rename(columns={"index": "gsis"})


def tag_for(gap4, dsnap) -> list[str]:
    tags = []
    if gap4 == gap4 and gap4 >= BUY_LOW_GAP:
        tags.append("buy low")
    if gap4 == gap4 and gap4 <= SELL_HIGH_GAP:
        tags.append("sell high")
    if dsnap == dsnap and dsnap >= ROLE_GROWING:
        tags.append("role growing")
    return tags


class Regression(Module):
    name = "Opportunity vs. production + role trend"
    kind = "regression"

    def __init__(self, coefs=None, signals=("gap4", "dsnap")):
        super().__init__(coefs)
        self.signals = tuple(signals)

    def _X(self, s, m):
        cols = []
        if "gap4" in self.signals:
            cols.append(s.gap4.fillna(0)[m].to_numpy())
        if "dsnap" in self.signals:
            cols.append(s.dsnap.fillna(0)[m].to_numpy() * 10)
        return np.c_[tuple(cols)] if cols else np.zeros((int(m.sum()), 0))

    def _sig(self, h, rows):
        if getattr(self, "override", None) is not None:          # live: signals computed as-of the upcoming game
            return rows[["gsis"]].merge(self.override, on="gsis", how="left").set_index(rows.index)
        s = build_signals(h)
        return rows[["gsis", "t"]].merge(s, on=["gsis", "t"], how="left").set_index(rows.index)

    def fit(self, h, rows):
        s = self._sig(h, rows)
        self.coefs = {}
        for pos in POS:
            m = ((rows.pos == pos) & s.gap4.notna()).to_numpy()
            y = (rows.pts - rows.base)[m].to_numpy()
            self.coefs[pos] = ols_through_origin(self._X(s, m), y, ridge=100.0).tolist()
        return self

    def predict(self, h, rows):
        out = empty_pred(rows.index)
        s = self._sig(h, rows)
        for pos in POS:
            m = ((rows.pos == pos) & s.gap4.notna()).to_numpy()
            if pos in self.coefs and m.any():
                out.loc[m, "delta"] = self._X(s, m) @ np.array(self.coefs[pos])
        reasons = []
        for d, g, ds in zip(out["delta"], s.gap4, s.dsnap):
            if abs(d) < 0.25:
                reasons.append("")
                continue
            bits = []
            if g == g and abs(g) >= 1.0:
                bits.append(f"his opportunities were worth {g:.1f} more pts/game than he scored over his last 4 (under-performing; expect a bounce)" if g > 0 else
                            f"he scored {-g:.1f} more pts/game than his opportunities were worth over his last 4 (over-performing; expect a fade)")
            if ds == ds and abs(ds) >= 0.05:
                bits.append(f"snap share {'up' if ds > 0 else 'down'} {abs(ds) * 100:.0f} pts recently")
            reasons.append("; ".join(bits) + f" → {d:+.1f}")
        out["reason"] = reasons
        out["confidence"] = "low"
        return out
