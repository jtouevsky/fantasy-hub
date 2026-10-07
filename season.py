"""Season model v2: week-by-week expected points, injury return timelines, signed value (no clipping), exact lineup totals.

* A player's expected points in week w = P(available in w) x projection(w).
    - w == this week: ESPN's projection plus the edge engine's adjustments (PlayerInfo.week_proj).
    - w  > this week: smoothed per-game points plus the edge engine's rest-of-season adjustment.
* Availability: bye weeks are 0; injuries follow a return TIMELINE (news-derived games missed if known, otherwise status defaults),
  with uncertainty, a re-injury discount and a rust factor right after return - never a flat 0.5.
* Value = points above replacement, SIGNED (negative allowed), plus raw rest-of-season points. Nothing is clipped to 0.
* Team value = the optimal starting lineup each remaining week (byes, return weeks, playoff weeks weighted), not a sum of player values.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

from models import LeagueSnapshot, PlayerInfo
from optimizer import best_lineup
from strategy import Strategy
from valuation import ValueModel

IR_DEFAULT_GAMES = 6.0          # expected games still to miss for an IR player when no news gives a timeline (NFL IR minimum is 4)
OUT_DEFAULT_GAMES = 1.5         # Out but not IR
SUSPENDED_DEFAULT_GAMES = 3.0
REINJURY_DISCOUNT = 0.92        # a returning player is slightly less likely to be available each remaining week
RUST = {0: 0.88, 1: 0.95}       # production multiplier in the first two weeks after the expected return
QUESTIONABLE_P_OUT = 0.41       # share of Questionable players who sit (nflverse history, see docs/backtest.md); only this week
DOUBTFUL_P_OUT = 0.9


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class Timeline:
    """Human-readable injury outlook for a player (what the UI tag says)."""
    status: str
    expected_games_out: float
    source: str               # 'news' | 'default'
    return_week: Optional[int]
    note: str


class Season:
    def __init__(self, snap: LeagueSnapshot, model: ValueModel, strategy: Strategy, fas: Iterable[PlayerInfo] = (), pool_per_pos: Optional[dict] = None):
        self.snap, self.model, self.strategy = snap, model, strategy
        self.week, self.final, self.reg = snap.week, snap.final_week, snap.reg_season_weeks
        self.weeks = list(range(self.week, self.final + 1)) or [self.week]
        self.weights = {w: (strategy.playoff_weight if w > self.reg else 1.0) for w in self.weeks}
        self.starters = snap.starter_slots
        self.capacity = sum(snap.starter_slots.values()) + snap.bench_slots
        self._exp: dict[tuple[int, int], float] = {}
        self.fa_pool = self._build_pool(list(fas), pool_per_pos or {"QB": 1, "RB": 3, "WR": 3, "TE": 1, "D/ST": 1})

    # ---- availability ---------------------------------------------------------
    def timeline(self, p: PlayerInfo) -> Timeline:
        st = p.injury_status
        known = p.return_games >= 0
        if st in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
            games = p.return_games if known else {"INJURY_RESERVE": IR_DEFAULT_GAMES, "OUT": OUT_DEFAULT_GAMES, "SUSPENSION": SUSPENDED_DEFAULT_GAMES}[st]
            ret = self.week + int(round(games))
            kind = {"INJURY_RESERVE": "IR", "OUT": "Out", "SUSPENSION": "Suspended"}[st]
            return Timeline(kind, games, "news" if known else "default", ret if ret <= self.final else None,
                            f"{kind}; about {games:.0f} more game{'s' if round(games) != 1 else ''} missed ({'from news' if known else 'typical for this status; no timeline in the news'})"
                            + (f", back around week {ret}" if ret <= self.final else ", likely out for the rest of the fantasy season"))
        if st == "DOUBTFUL":
            return Timeline("Doubtful", 0.9, "default", self.week + 1, "Doubtful this week; expected back next week")
        if st == "QUESTIONABLE":
            return Timeline("Questionable", 0.4, "default", None, "Questionable: sits about 4 times in 10; healthy afterwards")
        return Timeline("Healthy", 0.0, "default", None, "Healthy")

    def avail(self, p: PlayerInfo, w: int) -> float:
        if p.bye_week and p.bye_week == w:
            return 0.0
        if w == self.week and p.on_bye:
            return 0.0
        st, k = p.injury_status, w - self.week
        if st == "QUESTIONABLE":
            return 1.0 - QUESTIONABLE_P_OUT if k == 0 else 1.0
        if st == "DOUBTFUL":
            return 1.0 - DOUBTFUL_P_OUT if k == 0 else 1.0
        if st in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
            e = self.timeline(p).expected_games_out
            sigma = max(0.7, 0.5 * e) if p.return_games < 0 else max(0.5, 0.25 * e)       # known timelines are tighter
            ret_prob = _phi((k - e + 0.5) / sigma)
            return ret_prob * (REINJURY_DISCOUNT if st == "INJURY_RESERVE" else 1.0)
        return 1.0

    def rust(self, p: PlayerInfo, w: int) -> float:
        if p.injury_status not in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
            return 1.0
        ret = self.week + int(round(self.timeline(p).expected_games_out))
        return RUST.get(w - ret, 1.0)

    # ---- points -------------------------------------------------------------------
    def pts(self, p: PlayerInfo, w: int) -> float:
        """Points if he plays in week w."""
        if w == self.week and p.injury_status in ("ACTIVE", "QUESTIONABLE", "DOUBTFUL"):
            return p.week_proj
        return self.model.ppg(p)

    def exp(self, p: PlayerInfo, w: int) -> float:
        key = (p.player_id, w)
        v = self._exp.get(key)
        if v is None:
            v = self._exp[key] = self.avail(p, w) * self.rust(p, w) * self.pts(p, w)
        return v

    def raw_ros(self, p: PlayerInfo) -> float:
        """Weighted expected points over the rest of the fantasy season (availability and byes included)."""
        return sum(self.weights[w] * self.exp(p, w) for w in self.weeks)

    def par(self, p: PlayerInfo) -> float:
        """My value: weighted points above replacement while he is available. SIGNED: a below-replacement player is negative, not 0."""
        repl = self.model.replacement_ppg.get(p.position, 0.0)
        return sum(self.weights[w] * self.avail(p, w) * self.rust(p, w) * (self.pts(p, w) - repl) for w in self.weeks)

    def healthy_par(self, p: PlayerInfo) -> float:
        """Same as par() but as if healthy (byes still count): the scale market values are expressed in."""
        repl = self.model.replacement_ppg.get(p.position, 0.0)
        return sum(self.weights[w] * (0.0 if (p.bye_week == w) else (self.pts(p, w) if (w != self.week or p.injury_status == "ACTIVE") else self.model.ppg(p)) - repl) for w in self.weeks)

    def upside(self, p: PlayerInfo) -> float:
        """How far above his current level the evidence says he could go (ESPN season projection, buy-low tag, rest-of-season edge)."""
        gap = max(0.0, p.season_proj_ppg - self.model.ppg(p)) + max(0.0, p.edge_ros)
        if any(t[0] == "buy low" for t in p.tags):
            gap += 1.0
        return gap * sum(self.weights[w] * self.avail(p, w) for w in self.weeks) * 0.5

    def rank_key(self, p: PlayerInfo) -> float:
        """Ordering for bench/drop decisions: raw points + upside. Never a pile of identical zeros."""
        return self.raw_ros(p) + self.upside(p)

    # ---- lineups --------------------------------------------------------------------
    def _build_pool(self, fas: list[PlayerInfo], per_pos: dict) -> list[PlayerInfo]:
        by: dict[str, list[PlayerInfo]] = {}
        for p in fas:
            by.setdefault(p.position, []).append(p)
        pool = []
        for pos, n in per_pos.items():
            pool += sorted(by.get(pos, []), key=lambda p: -self.raw_ros_noncached(p))[:n]
        return pool

    def raw_ros_noncached(self, p: PlayerInfo) -> float:
        return sum(self.weights[w] * self.avail(p, w) * self.pts(p, w) for w in self.weeks)

    def week_value(self, roster: list[PlayerInfo], w: int, use_pool: bool = True) -> tuple[float, list[PlayerInfo]]:
        """Best expected starting-lineup points in week w. Holes are filled by the best ACTUAL free agent in this league."""
        cands = list(roster) + (self.fa_pool if use_pool else [])
        best = best_lineup(cands, self.starters, value=lambda p: self.exp(p, w), eligible=lambda p: True)
        chosen = [p for p in best.values() if p]
        return sum(self.exp(p, w) for p in chosen), chosen

    def season_lineup(self, roster: list[PlayerInfo], use_pool: bool = True) -> dict:
        """{'total': weighted sum over remaining weeks, 'weeks': [(week, points)], 'starts': {pid: weeks started}}."""
        weeks, starts, total = [], {}, 0.0
        for w in self.weeks:
            v, chosen = self.week_value(roster, w, use_pool)
            weeks.append((w, v))
            total += self.weights[w] * v
            for p in chosen:
                starts[p.player_id] = starts.get(p.player_id, 0) + 1
        return {"total": total, "weeks": weeks, "starts": starts}

    # ---- roster spots ---------------------------------------------------------------
    def roster_count(self, roster: list[PlayerInfo]) -> int:
        """Players that occupy a regular (non-IR) roster spot. A player in an IR slot costs no bench spot."""
        return sum(1 for p in roster if p.lineup_slot != "IR")

    def worst_droppable(self, roster: list[PlayerInfo], protect: Optional[set[int]] = None) -> Optional[PlayerInfo]:
        """The least valuable player who could be cut to make room (never someone in an IR slot; never a protected id)."""
        protect = protect or set()
        cands = [p for p in roster if p.lineup_slot != "IR" and p.player_id not in protect]
        return min(cands, key=self.rank_key) if cands else None
