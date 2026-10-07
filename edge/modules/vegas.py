"""Module 3: game environment from Vegas lines.

Implied team total = total/2 +/- spread/2. Players on teams expected to score more than their own recent average get a lift
(and vice versa); big favorites run more (RBs up), big underdogs throw more (pass catchers up). Coefficients are fit by
least squares on 2024 residuals (actual - baseline), per position, as a proportion of each player's baseline.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.modules.base import Module, empty_pred, ols_through_origin

POS = ["QB", "RB", "WR", "TE"]


class Vegas(Module):
    name = "Game environment (Vegas)"
    kind = "vegas"

    def fit(self, h, rows):
        for pos in POS:
            r = rows[(rows.pos == pos) & rows.x_imp.notna() & rows.spread.notna()]
            X = np.c_[r.base * r.x_imp / 10, r.base * r.spread / 10]
            y = (r.pts - r.base).to_numpy()
            self.coefs[pos] = ols_through_origin(X, y, ridge=50.0).tolist()
        return self

    def predict(self, h, rows):
        out = empty_pred(rows.index)
        for pos in POS:
            m = (rows.pos == pos) & rows.x_imp.notna() & rows.spread.notna()
            if pos not in self.coefs or not m.any():
                continue
            c_imp, c_spr = self.coefs[pos]
            r = rows[m]
            out.loc[m, "delta"] = r.base * (c_imp * r.x_imp + c_spr * r.spread) / 10
        d = out["delta"]
        out["reason"] = [
            (f"{r.team} implied {r.implied:.1f} pts vs their {r.implied - r.x_imp:.1f} avg"
             + (f"; {'favored' if r.spread > 0 else 'underdog'} by {abs(r.spread):.1f}" if abs(r.spread) >= 3 else "")
             + f" → {x:+.1f}") if abs(x) >= 0.25 else "" for r, x in zip(rows.itertuples(), d)]
        out["confidence"] = np.where(d.abs() >= 1.5, "med", "low")
        return out
