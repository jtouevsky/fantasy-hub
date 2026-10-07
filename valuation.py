"""Player value model. Simple and transparent; see the README for the formula.

    ppg        = (games_played * actual_ppg + K * projected_ppg) / (games_played + K)     K = 4
    games_left = weeks from now to the end of the fantasy season, minus the NFL bye if still ahead
    ros_points = ppg * games_left * availability(injury)
    value      = max(0, ppg - replacement_ppg[position]) * games_left * availability     # "points over replacement"

replacement_ppg[pos] = ppg of the first player NOT starting league-wide at that position.
"How many start" is measured, not assumed: every team's optimal lineup is solved with the league's
real slot settings, so FLEX/OP slots are allotted to RB/WR/TE/QB by who actually fills them.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from models import LeagueSnapshot, PlayerInfo
from optimizer import best_lineup

K_PRIOR_GAMES = 4
PACKAGE_DEPTH_WEIGHT = 0.6      # 2nd, 3rd... player in a package count 60% (roster spots are limited)
# Long-run availability (how much of the remaining season we expect them to play).
ROS_AVAILABILITY = {
    "ACTIVE": 1.0, "QUESTIONABLE": 0.97, "DOUBTFUL": 0.85, "OUT": 0.75,
    "INJURY_RESERVE": 0.5, "SUSPENSION": 0.7,
}


def blended_ppg(p: PlayerInfo, k: float = K_PRIOR_GAMES) -> float:
    proj = p.season_proj_ppg
    if p.games_played <= 0:
        return proj
    if proj <= 0:
        return p.actual_ppg
    return (p.games_played * p.actual_ppg + k * proj) / (p.games_played + k)


def ros_availability(p: PlayerInfo) -> float:
    return ROS_AVAILABILITY.get(p.injury_status, 0.9)


def games_remaining(p: PlayerInfo, week: int, final_week: int) -> int:
    n = max(final_week - week + 1, 0)
    if p.bye_week and week <= p.bye_week <= final_week and not (p.bye_week == week and not p.on_bye):
        n -= 1
    return max(n, 0)


class ValueModel:
    def __init__(self, snap: LeagueSnapshot, free_agents: Optional[list[PlayerInfo]] = None):
        self.snap = snap
        self.week, self.final_week = snap.week, snap.final_week
        self.starters = snap.starter_slots
        self.starters_by_pos = self._count_league_starters()
        self.replacement_ppg = self._replacement_levels(free_agents or [])

    # -- per-player numbers -------------------------------------------------
    def games_left(self, p: PlayerInfo) -> int:
        return games_remaining(p, self.week, self.final_week)

    def ppg(self, p: PlayerInfo) -> float:
        return blended_ppg(p)

    def ros_points(self, p: PlayerInfo) -> float:
        return self.ppg(p) * self.games_left(p) * ros_availability(p)

    def value(self, p: PlayerInfo) -> float:
        """Rest-of-season points over replacement (0 for players below replacement)."""
        repl = self.replacement_ppg.get(p.position)
        if repl is None:
            return 0.0
        return max(0.0, self.ppg(p) - repl) * self.games_left(p) * ros_availability(p)

    def lineup_ppg(self, roster: list[PlayerInfo]) -> float:
        """Weekly points of a roster's best lineup using smoothed per-game numbers (injuries/byes ignored)."""
        best = best_lineup(roster, self.starters, value=self.ppg, eligible=lambda p: True)
        return sum(self.ppg(p) for p in best.values() if p)

    def lineup_value_ros(self, roster: list[PlayerInfo]) -> float:
        """Total ROS value of the starters in the roster's best lineup (accounts for injuries/byes)."""
        score = lambda p: self.ppg(p) * ros_availability(p)
        best = best_lineup(roster, self.starters, value=score, eligible=lambda p: True)
        return sum(self.ros_points(p) for p in best.values() if p)

    def package_value(self, players: list[PlayerInfo]) -> float:
        vals = sorted((self.value(p) for p in players), reverse=True)
        return sum(v * (1.0 if i == 0 else PACKAGE_DEPTH_WEIGHT) for i, v in enumerate(vals))

    # -- setup ----------------------------------------------------------------
    def _count_league_starters(self) -> Counter:
        counts: Counter = Counter()
        for t in self.snap.teams:
            best = best_lineup(t.roster, self.starters, value=self.ppg, eligible=lambda p: True)
            counts.update(p.position for p in best.values() if p)
        return counts

    def _replacement_levels(self, fas: list[PlayerInfo]) -> dict[str, float]:
        pool = [p for t in self.snap.teams for p in t.roster] + list(fas)
        out: dict[str, float] = {}
        for pos, n_start in self.starters_by_pos.items():
            ppgs = sorted((self.ppg(p) for p in pool if p.position == pos and p.injury_status != "INJURY_RESERVE"), reverse=True)
            if not ppgs:
                continue
            out[pos] = ppgs[n_start] if len(ppgs) > n_start else ppgs[-1]
        return out


def fairness(value_get: float, value_give: float) -> tuple[float, float]:
    """Return (my_share, their_share) in percent. 60/40 means I receive 60% of the combined value."""
    total = value_get + value_give
    if total <= 0:
        return 50.0, 50.0
    return round(100 * value_get / total, 1), round(100 * value_give / total, 1)
