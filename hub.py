"""One bundle of the v2 engines (strategy, season model, market, trade world, move engine) built once per data refresh.

Every surface (Waivers page, optimizer, Overview cards, Trades page, the AI assistant) asks the SAME Hub, so numbers and recommendations
cannot disagree and the assistant never does its own valuation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import strategy as strategy_mod
import trading
from models import LeagueSnapshot, PlayerInfo
from moves import MoveEngine
from season import Season
from strategy import Strategy
from valuation import ValueModel


@dataclass
class Hub:
    strategy: Strategy
    season: Season
    world: trading.TradeWorld
    moves: MoveEngine

    @property
    def market(self):
        return self.world.market


def apply_activity(snap: LeagueSnapshot, activity: list[dict]) -> None:
    """Stamp `added_ts` on my players from the league's recent-activity feed (used for recently-added protection)."""
    mine = {p.player_id: p for p in snap.my_team.roster}
    for a in activity:
        if a.get("team_id") == snap.my_team.team_id and "ADDED" in a.get("action", "") and a.get("player_id") in mine:
            p = mine[a["player_id"]]
            p.added_ts = max(p.added_ts, float(a.get("ts", 0.0)))


def apply_return_games(players: list[PlayerInfo], edge_res) -> int:
    """Copy news/engine-derived games-missed estimates onto injured players (drives the IR return timeline)."""
    n = 0
    if edge_res is None:
        return n
    for p in players:
        if p.injury_status not in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
            continue
        gsis = edge_res.gsis_of.get(p.player_id)
        st = edge_res.injuries.get(gsis) if gsis else None
        if st is not None and st.games_missed is not None:
            p.return_games, n = float(st.games_missed), n + 1
    return n


def build(snap: LeagueSnapshot, model: ValueModel, fas: list[PlayerInfo], db_path: Optional[str] = None, market_signals: Optional[dict] = None,
          activity: Optional[list[dict]] = None, dst: Optional[dict] = None, dst_next: Optional[dict] = None, strat: Optional[Strategy] = None) -> Hub:
    strat = strat or strategy_mod.load(db_path)
    activity = list(activity or [])
    apply_activity(snap, activity)
    world = trading.make_world(snap, list(fas), model, strat, market_signals or {}, activity, db_path)
    eng = MoveEngine(snap, world.season, strat, list(fas), activity, dst=dst, dst_next=dst_next)
    return Hub(strat, world.season, world, eng)
