"""Shared pre-game features for the backtest evaluation frame (everything here uses only information available before kickoff)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.history import Hist

LEAGUE_IMPLIED = 22.5
OUTDOOR = {"outdoors", "open"}


def eval_frame(h: Hist, seasons: list[int], weeks=range(3, 19), min_prev: int = 2, min_base: float = 3.0) -> pd.DataFrame:
    """Player-games to score: played, >= min_prev prior games, baseline >= min_base (fantasy-relevant)."""
    b = h.with_baseline()
    b = b.merge(game_context(h), on=["season", "week", "team"], how="left", suffixes=("", "_g"))
    e = b[b.season.isin(seasons) & b.week.isin(list(weeks)) & (b.n_prev >= min_prev) & (b.base >= min_base)].copy()
    return e.reset_index(drop=True)


def game_context(h: Hist) -> pd.DataFrame:
    """Per team-game: Vegas implied total vs the team's own trailing average, weather flags. Pre-game info only."""
    g = h.games.sort_values(["team", "t"]).copy()
    # trailing mean of the team's previous implied totals (this season; falls back to the league mean for week 1-2)
    g["prev_implied"] = g.groupby(["team", "season"])["implied"].transform(lambda s: s.shift(1).expanding().mean())
    g["prev_implied"] = g["prev_implied"].fillna(LEAGUE_IMPLIED)
    g["x_imp"] = g["implied"] - g["prev_implied"]
    g["outdoor"] = g["roof"].isin(OUTDOOR)
    g["wind15"] = (g["outdoor"] & (g["wind"] >= 15)).astype(float)
    g["cold"] = (g["outdoor"] & (g["temp"] <= 25)).astype(float)
    return g[["season", "week", "team", "opp", "home", "spread", "total", "implied", "opp_implied", "x_imp", "wind", "temp", "roof",
              "outdoor", "wind15", "cold", "game_id", "gameday", "gametime"]].rename(columns={"opp": "opp_g"})
