"""Module 4: weather. Wind >= 15 mph (outdoor stadiums only) and extreme cold hurt the passing game; domes get nothing.

Historical wind/temperature come from nflverse schedules (actual conditions, a proxy for a game-day forecast); live runs use
Open-Meteo forecasts. Precipitation is not in the historical schedule table, so it is NOT part of the validated model.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.modules.base import Module, empty_pred, ols_through_origin

POS = ["QB", "RB", "WR", "TE"]


class Weather(Module):
    name = "Weather"
    kind = "weather"

    def fit(self, h, rows):
        for pos in POS:
            r = rows[rows.pos == pos]
            X = np.c_[r.base * r.wind15.fillna(0), r.base * r.cold.fillna(0)]
            self.coefs[pos] = ols_through_origin(X, (r.pts - r.base).to_numpy(), ridge=5.0).tolist()
        return self

    def predict(self, h, rows):
        out = empty_pred(rows.index)
        for pos in POS:
            m = rows.pos == pos
            if pos not in self.coefs or not m.any():
                continue
            c_w, c_c = self.coefs[pos]
            r = rows[m]
            out.loc[m, "delta"] = r.base * (c_w * r.wind15.fillna(0) + c_c * r.cold.fillna(0))
        out["reason"] = [
            (f"{'Wind ' + str(int(r.wind)) + ' mph' if r.wind15 else 'Cold ' + str(int(r.temp)) + '°F'} at an outdoor stadium → {x:+.1f}") if abs(x) >= 0.25 else ""
            for r, x in zip(rows.itertuples(), out["delta"])]
        out["confidence"] = "low"
        return out
