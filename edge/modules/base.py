"""Module protocol shared by the backtest and the live engine.

A module is fit on historical rows (backtest, 2024) and then `predict`s deltas for any frame of player-games that has a
`base` column (ESPN's projection live; trailing 4-game mean in the backtest). The same `predict` code runs in both places,
so the backtest measures what actually ships.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.history import Hist


class Module:
    name = "module"
    kind = "vegas"            # adjustment type recorded in the database

    def __init__(self, coefs: dict | None = None):
        self.coefs: dict = coefs or {}

    # ---- required ----
    def fit(self, h: Hist, rows: pd.DataFrame) -> "Module":      # rows: training player-games (with base, pts)
        return self

    def predict(self, h: Hist, rows: pd.DataFrame) -> pd.DataFrame:
        """-> DataFrame indexed like `rows` with columns delta (float), reason (str), confidence (low/med/high)."""
        raise NotImplementedError

    def affected(self, pred: pd.DataFrame) -> pd.Series:
        """Which rows this module actually moves (used for 'affected rows' metrics)."""
        return pred["delta"].abs() >= 0.25


def ols_through_origin(X: np.ndarray, y: np.ndarray, ridge: float = 0.0) -> np.ndarray:
    """Least squares without intercept, optional ridge penalty (for tiny samples)."""
    if len(y) == 0:
        return np.zeros(X.shape[1])
    A = X.T @ X + ridge * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ y)


def empty_pred(index) -> pd.DataFrame:
    return pd.DataFrame({"delta": 0.0, "reason": "", "confidence": "low"}, index=index)
