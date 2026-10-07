"""nflverse history, joined by stable IDs, with 'as of week N' views that cannot leak the future.

Every table is a pandas DataFrame. `t = season*100 + week` orders games across seasons.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from edge import scoring
from edge.ids import norm_team

log = logging.getLogger("edge.history")
SKILL = ["QB", "RB", "WR", "TE"]
_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "nflverse_cache")


def _nfl():
    import nflreadpy as nfl
    from nflreadpy.config import update_config
    os.makedirs(_CACHE_DIR, exist_ok=True)
    from pathlib import Path
    update_config(cache_mode="filesystem", cache_dir=Path(_CACHE_DIR), cache_duration=6 * 3600)
    return nfl


def tkey(season, week):
    return season * 100 + week


@dataclass
class Hist:
    seasons: list[int]
    weekly: pd.DataFrame            # one row per player-game (REG season): gsis, name, pos, team, opp, season, week, t, pts, usage...
    games: pd.DataFrame             # one row per team-game: lines, implied totals, weather
    snaps: pd.DataFrame             # offense/defense snap shares per player-game, keyed by gsis
    inj: pd.DataFrame               # weekly injury report per player
    xfp: pd.DataFrame               # expected fantasy points (ff_opportunity)
    pbp_team: Optional[pd.DataFrame] = None   # team-week pass-rush / protection rates from play-by-play
    weights: dict = field(default_factory=dict)

    # ---- construction ---------------------------------------------------------
    @classmethod
    def load(cls, seasons: list[int], weights: Optional[dict[str, float]] = None, with_pbp: bool = False) -> "Hist":
        nfl = _nfl()
        w = weights or scoring.weights()
        ps = nfl.load_player_stats(seasons).to_pandas()
        ps = ps[(ps["season_type"] == "REG") & ps["position"].isin(SKILL)].copy()
        ps["team"] = ps["team"].map(norm_team)
        ps["opp"] = ps["opponent_team"].map(norm_team)
        ps["pts"] = scoring.points(ps, w)
        rush_w = {k: v for k, v in w.items() if k.startswith("rushing_")}
        rec_w = {k: v for k, v in w.items() if k.startswith("receiving_") or k == "receptions"}
        ps["rush_pts"] = scoring.points(ps, rush_w)          # points earned as a runner / as a receiver (for per-touch efficiency)
        ps["rec_pts"] = scoring.points(ps, rec_w)
        ps["gsis"] = ps["player_id"]
        ps["name"] = ps["player_display_name"]
        ps["pos"] = ps["position"]
        ps["t"] = tkey(ps["season"], ps["week"])
        keep = ["gsis", "name", "pos", "team", "opp", "season", "week", "t", "pts", "rush_pts", "rec_pts", "carries", "targets", "receptions", "attempts", "completions",
                "passing_yards", "passing_tds", "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds", "target_share", "sacks_suffered",
                "passing_interceptions", "air_yards_share", "wopr"]
        weekly = ps[[c for c in keep if c in ps.columns]].sort_values(["gsis", "t"]).reset_index(drop=True)

        sc = nfl.load_schedules(seasons).to_pandas()
        sc = sc[sc["game_type"] == "REG"]
        home = pd.DataFrame({"season": sc.season, "week": sc.week, "team": sc.home_team.map(norm_team), "opp": sc.away_team.map(norm_team), "home": 1,
                             "spread": sc.spread_line, "total": sc.total_line, "wind": sc.wind, "temp": sc.temp, "roof": sc.roof,
                             "gameday": sc.gameday, "gametime": sc.gametime, "game_id": sc.game_id, "stadium": sc.stadium})
        away = home.assign(team=sc.away_team.map(norm_team).values, opp=sc.home_team.map(norm_team).values, home=0, spread=-sc.spread_line.values)
        games = pd.concat([home, away], ignore_index=True)
        games["implied"] = games.total / 2 + games.spread / 2          # spread: positive = this team is favored
        games["opp_implied"] = games.total / 2 - games.spread / 2
        games["t"] = tkey(games.season, games.week)

        xw = nfl.load_ff_playerids().to_pandas()
        pfr2gsis = dict(zip(xw.pfr_id.dropna(), xw.loc[xw.pfr_id.notna(), "gsis_id"]))
        sn = nfl.load_snap_counts(seasons).to_pandas()
        sn = sn[sn["game_type"] == "REG"].copy()
        sn = sn.rename(columns={"position": "pos"})
        sn["gsis"] = sn["pfr_player_id"].map(pfr2gsis)
        sn["team"] = sn["team"].map(norm_team)
        sn["t"] = tkey(sn.season, sn.week)
        sn = sn[sn.gsis.notna()]

        inj = nfl.load_injuries(seasons).to_pandas()
        inj = inj[inj["game_type"] == "REG"] if "game_type" in inj else inj
        inj = inj.rename(columns={"gsis_id": "gsis", "position": "pos"})
        inj["team"] = inj["team"].map(norm_team)
        inj["t"] = tkey(inj.season, inj.week)

        ff = nfl.load_ff_opportunity(seasons).to_pandas()
        ff["season"] = ff["season"].astype(int)
        ff["week"] = ff["week"].astype(int)
        xfp = ff.rename(columns={"player_id": "gsis", "total_fantasy_points_exp": "xfp", "total_fantasy_points": "xfp_actual"})
        xfp["t"] = tkey(xfp.season, xfp.week)
        xfp = xfp[["gsis", "season", "week", "t", "xfp", "xfp_actual"]]
        pb = cls._pbp_team(nfl, seasons) if with_pbp else None
        return cls(seasons, weekly, games, sn, inj, xfp, pb, w)

    @staticmethod
    def _pbp_team(nfl, seasons) -> pd.DataFrame:
        """Team-week pass protection / pass rush rates from play-by-play (pressure proxy = sacks + QB hits per dropback)."""
        import polars as pl
        pbp = nfl.load_pbp(seasons).filter((pl.col("season_type") == "REG") & (pl.col("pass") == 1))
        off = pbp.group_by(["season", "week", "posteam"]).agg(
            pl.len().alias("db"), pl.col("sack").sum().alias("sacks"), pl.col("qb_hit").sum().alias("hits")).rename({"posteam": "team"}).to_pandas()
        off["press_allowed"] = (off.sacks + off.hits) / off.db
        dff = pbp.group_by(["season", "week", "defteam"]).agg(
            pl.len().alias("db"), pl.col("sack").sum().alias("sacks"), pl.col("qb_hit").sum().alias("hits")).rename({"defteam": "team"}).to_pandas()
        dff["press_made"] = (dff.sacks + dff.hits) / dff.db
        out = off[["season", "week", "team", "press_allowed"]].merge(dff[["season", "week", "team", "press_made"]], on=["season", "week", "team"], how="outer")
        out["team"] = out["team"].map(norm_team)
        out["t"] = tkey(out.season, out.week)
        return out

    # ---- baseline (what the engine adjusts when no ESPN projection exists) ---------------------
    def with_baseline(self, n: int = 4) -> pd.DataFrame:
        """weekly + base (trailing mean of the last `n` games played, across seasons) and n_prev; only past games are used."""
        w = self.weekly.copy()
        g = w.groupby("gsis")["pts"]
        w["n_prev"] = g.transform(lambda s: s.shift(1).rolling(n, min_periods=1).count())
        w["base"] = g.transform(lambda s: s.shift(1).rolling(n, min_periods=1).mean())
        return w
