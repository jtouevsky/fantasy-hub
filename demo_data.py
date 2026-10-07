"""Synthetic 10-team league used by tests and by DEMO_MODE (no ESPN credentials needed).
All players are obviously fake ("Demo ...") so nothing here is mistaken for real stats."""
from __future__ import annotations

import random
import time

from models import LeagueSnapshot, MatchupInfo, Owner, PlayerInfo, TeamInfo

STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "D/ST": 1, "K": 1}
ELIGIBLE = {
    "QB": ["QB", "OP"], "RB": ["RB", "RB/WR", "FLEX", "OP"], "WR": ["WR", "RB/WR", "WR/TE", "FLEX", "OP"],
    "TE": ["TE", "WR/TE", "FLEX", "OP"], "K": ["K"], "D/ST": ["D/ST"],
}
OWNER_NAMES = ["Jordan", "Kaden", "Riley", "Sam", "Alex", "Morgan", "Taylor", "Casey", "Drew", "Jamie"]
# (position, count per team, top-end ppg, ppg drop per depth step)
_SHAPE = [("QB", 2, 21, 4), ("RB", 5, 16, 2.6), ("WR", 5, 16, 2.4), ("TE", 2, 12, 4), ("K", 1, 8, 0), ("D/ST", 1, 8, 0)]
NFL = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC"]


def _player(pid: int, pos: str, ppg: float, rnd: random.Random, week: int, owner: int | None) -> PlayerInfo:
    team = rnd.choice(NFL)
    return PlayerInfo(
        player_id=pid, name=f"Demo {pos} {pid}", position=pos, pro_team=team,
        eligible_slots=ELIGIBLE[pos] + ["BE"], week_proj=round(ppg * rnd.uniform(0.85, 1.1), 1),
        total_points=round(ppg * (week - 1) * rnd.uniform(0.8, 1.1), 1), games_played=week - 1,
        season_proj_ppg=round(ppg, 1), percent_owned=round(rnd.uniform(20, 99), 1),
        bye_week=rnd.randint(5, 14), opponent=rnd.choice(NFL), owner_team_id=owner,
    )


def assign_slots(roster: list[PlayerInfo], starters: dict[str, int] = STARTERS) -> None:
    """Naive 'current lineup': best by position, then flex. Deliberately imperfect so the optimizer has work."""
    for p in roster:
        p.lineup_slot = "BE"
    by_pos = lambda pos: sorted([p for p in roster if p.position == pos], key=lambda p: -p.season_proj_ppg)
    for pos in ("QB", "RB", "WR", "TE", "K", "D/ST"):
        for p in by_pos(pos)[: starters.get(pos, 0)]:
            p.lineup_slot = pos
    flex_pool = [p for p in roster if p.lineup_slot == "BE" and p.position in ("RB", "WR", "TE")]
    for p in sorted(flex_pool, key=lambda p: -p.season_proj_ppg)[: starters.get("FLEX", 0)]:
        p.lineup_slot = "FLEX"


def build_demo_snapshot(week: int = 5, seed: int = 7, my_team_id: int = 1) -> LeagueSnapshot:
    rnd = random.Random(seed)
    pid = 1000
    teams = []
    for tid in range(1, 11):
        roster = []
        for pos, n, top, step in _SHAPE:
            for depth in range(n):
                pid += 1
                ppg = max(top - step * depth + rnd.uniform(-2.5, 2.5), 2.0)
                roster.append(_player(pid, pos, ppg, rnd, week, tid))
        assign_slots(roster)
        w = rnd.randint(1, week - 1)
        teams.append(TeamInfo(
            team_id=tid, name=f"Demo Team {tid}", abbrev=f"T{tid}",
            owners=[Owner(OWNER_NAMES[tid - 1], "Demo", OWNER_NAMES[tid - 1].lower())],
            wins=w, losses=week - 1 - w, points_for=round(rnd.uniform(90, 130) * (week - 1), 1),
            points_against=round(rnd.uniform(90, 130) * (week - 1), 1), standing=tid, roster=roster,
        ))
    matchups = []
    for a in range(1, 11, 2):
        t1, t2 = teams[a - 1], teams[a]
        proj = lambda t: round(sum(p.week_proj for p in t.roster if p.lineup_slot not in ("BE", "IR")), 1)
        matchups.append(MatchupInfo(week, t1.team_id, t2.team_id, 0.0, 0.0, proj(t1), proj(t2)))
    return LeagueSnapshot(
        league_name="Demo League (fake data)", year=2026, week=week, final_week=17, reg_season_weeks=14,
        team_count=10, my_team_id=my_team_id, starter_slots=dict(STARTERS), bench_slots=6, ir_slots=1,
        scoring_notes={"points_per_reception": 1.0}, teams=teams, matchups=matchups, fetched_at=time.time(),
    )


def build_demo_free_agents(week: int = 5, seed: int = 99) -> list[PlayerInfo]:
    rnd = random.Random(seed)
    out, pid = [], 5000
    for pos, n, ppg in [("QB", 6, 15), ("RB", 14, 11), ("WR", 14, 11), ("TE", 8, 8), ("K", 5, 8), ("D/ST", 6, 7.5)]:
        for i in range(n):
            pid += 1
            p = _player(pid, pos, max(ppg - i * 0.9 + rnd.uniform(-2, 2), 1.5), rnd, week, None)
            p.lineup_slot = "FA"
            p.percent_owned = round(max(5, 70 - i * 6 + rnd.uniform(-5, 5)), 1)
            out.append(p)
    return out
