"""Market value: what OTHER managers think a player is worth, on the same scale (points above replacement) as my value.

Built only from signals ESPN publishes for every player (consensus, not my model):
    ros_rank   expert-consensus rest-of-season rank within the position   (how analysts rank him from here)
    auction    average auction value                                      (what drafters paid)
    adp        average draft position                                     (preseason consensus)
    ppr_rank   ESPN's PPR draft rank
    production this season's points per game vs. replacement              (what has actually happened)
    started    % of leagues starting him (only for healthy players: injured stars stay valued)
Each signal is converted to points by matching it to the same percentile of the league's HEALTHY value distribution (a pure rank ->
points scale transfer; the ORDER comes from the market, the SCALE from the league). Components are blended with the weights below.

No external trade-value chart is scraped. KeepTradeCut / FantasyCalc / FantasyPros each have their own terms; none is used here (see
docs/trade-engine-v2.md for the check).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from models import PlayerInfo
from season import Season

WEIGHTS = {"ros_rank": 0.35, "auction": 0.25, "adp": 0.15, "production": 0.15, "ppr_rank": 0.05, "started": 0.05}
CONSOLIDATION = 0.35        # extra worth of an elite asset: worth(v) = v * (1 + CONSOLIDATION * min(v / v_elite, 1)) for v > 0
SOFT_FLOOR = 2.0


def soft(v: float) -> float:
    """Smooth positive transform for RATIOS only (so split math never divides by 0 or a negative). Order-preserving, never clips to 0."""
    return v if v >= SOFT_FLOOR else SOFT_FLOOR * float(np.exp((v - SOFT_FLOOR) / SOFT_FLOOR))


@dataclass
class MarketRow:
    value: float
    components: dict
    has_market: bool
    brand: float                # market minus production: how much of his price is name/reputation rather than results


class Market:
    def __init__(self, season: Season, players: list[PlayerInfo]):
        self.season = season
        pool = [p for p in players if p.position in ("QB", "RB", "WR", "TE", "D/ST")]
        self._hp = {p.player_id: season.healthy_par(p) for p in pool}
        self.dist = sorted(self._hp.values(), reverse=True)
        self.by_pos = {pos: sorted((self._hp[p.player_id] for p in pool if p.position == pos), reverse=True) for pos in {p.position for p in pool}}
        elite = [v for v in self.dist if v > 0]
        self.v_elite = float(np.percentile(elite, 85)) if elite else 1.0
        self._sig = {}
        for key, rev in (("auction", True), ("adp", False), ("ppr_rank", False), ("started", True)):
            vals = sorted(((p.market[key], p.player_id) for p in pool if key in p.market), reverse=rev)
            n = max(len(vals) - 1, 1)
            self._sig[key] = {pid: i / n for i, (_, pid) in enumerate(vals)}
        prod = sorted(((self._production(p), p.player_id) for p in pool if p.games_played >= 2), reverse=True)
        n = max(len(prod) - 1, 1)
        self._sig["production"] = {pid: i / n for i, (_, pid) in enumerate(prod)}
        self._cache: dict[int, MarketRow] = {}
        self.pool_ids = {p.player_id for p in pool}

    def _production(self, p: PlayerInfo) -> float:
        return (p.actual_ppg - self.season.model.replacement_ppg.get(p.position, 0.0)) * 10          # per-game, position-adjusted

    def _at_pct(self, pct: float) -> float:
        d = self.dist
        if not d:
            return 0.0
        x = min(max(pct, 0.0), 1.0) * (len(d) - 1)
        i = int(x)
        return d[i] if i >= len(d) - 1 else d[i] + (d[i + 1] - d[i]) * (x - i)

    def _at_pos_rank(self, pos: str, rank: float) -> Optional[float]:
        d = self.by_pos.get(pos)
        if not d:
            return None
        x = min(max(rank - 1.0, 0.0), len(d) - 1)
        i = int(x)
        return d[i] if i >= len(d) - 1 else d[i] + (d[i + 1] - d[i]) * (x - i)

    def row(self, p: PlayerInfo) -> MarketRow:
        r = self._cache.get(p.player_id)
        if r is not None:
            return r
        comps: dict[str, float] = {}
        mk = p.market or {}
        if "ros_pos_rank" in mk:
            v = self._at_pos_rank(p.position, mk["ros_pos_rank"])
            if v is not None:
                comps["ros_rank"] = v
        for key in ("auction", "adp", "ppr_rank"):
            pct = self._sig[key].get(p.player_id)
            if pct is not None:
                comps[key] = self._at_pct(pct)
        pct = self._sig["production"].get(p.player_id)
        if pct is not None:
            comps["production"] = self._at_pct(pct)
        if p.injury_status == "ACTIVE" and not p.on_bye:
            pct = self._sig["started"].get(p.player_id)
            if pct is not None:
                comps["started"] = self._at_pct(pct)
        market_only = {k: v for k, v in comps.items() if k != "production"}
        if comps:
            w = {k: WEIGHTS[k] for k in comps}
            val = sum(comps[k] * w[k] for k in comps) / sum(w.values())
            row = MarketRow(val, comps, bool(market_only), val - comps.get("production", val))
        else:                                                   # no consensus data at all: fall back to my own healthy value, flagged
            row = MarketRow(self.season.healthy_par(p), {}, False, 0.0)
        self._cache[p.player_id] = row
        return row

    def value(self, p: PlayerInfo) -> float:
        return self.row(p).value

    def worth(self, v: float) -> float:
        """Consolidation premium: elite assets are scarce, so one star is worth more than the same points spread over two players."""
        v = soft(v)
        return v * (1.0 + CONSOLIDATION * min(v / self.v_elite, 1.0))

    def package(self, players: list[PlayerInfo]) -> float:
        return sum(self.worth(self.value(p)) for p in players)

    def explain(self, p: PlayerInfo) -> str:
        r = self.row(p)
        labels = {"ros_rank": "expert ROS rank", "auction": "avg auction value", "adp": "ADP", "ppr_rank": "PPR draft rank", "production": "production", "started": "% started"}
        return ", ".join(f"{labels[k]} {v:+.0f}" for k, v in sorted(r.components.items(), key=lambda kv: -WEIGHTS[kv[0]]))
