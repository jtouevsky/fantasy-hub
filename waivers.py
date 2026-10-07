"""Waiver wire: rank free agents and suggest add/drop pairs.

Each (add, drop) pair is scored by re-solving MY lineup with and without the move, so positional
need, bye/injury coverage and bench depth all fall out of the math instead of hand-written rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models import LeagueSnapshot, PlayerInfo
from optimizer import availability, best_lineup, can_start
from sleeper import SleeperIndex
from valuation import ValueModel

BREAKOUT_MAX_OWNED = 50.0       # trending AND under this % owned => "breakout" flag
MIN_SCORE = 1.0                 # ignore moves worth less than this many points
MAX_PER_POSITION = 2
DEPTH_WEIGHT = 0.15             # credit for a pure bench upgrade (ROS points difference * this)


@dataclass
class FreeAgentRank:
    player: PlayerInfo
    ros_value: float
    week_value: float
    trending_adds: int = 0
    breakout: bool = False
    tags: tuple = ()
    edge_reason: str = ""


@dataclass
class AddDrop:
    add: PlayerInfo
    drop: PlayerInfo
    weekly_gain: float          # points this week
    ros_gain_total: float       # points over the rest of the season (lineup effect only)
    ppg_gain: float             # average points per week gained
    score: float
    reason: str
    trending_adds: int = 0

    def action(self) -> str:
        return (f"In the ESPN app: place a waiver claim / add {self.add.name} ({self.add.position}, {self.add.pro_team}) "
                f"and drop {self.drop.name}. Waiver claims process on your league's waiver day.")


def rank_free_agents(model: ValueModel, fas: list[PlayerInfo], sleeper_index: Optional[SleeperIndex] = None,
                     trending: Optional[dict[str, int]] = None) -> list[FreeAgentRank]:
    trending = trending or {}
    out = []
    for p in fas:
        adds = 0
        if sleeper_index is not None:
            sid = sleeper_index.find(p)
            adds = trending.get(sid, 0) if sid else 0
        week = availability(p) if can_start(p) else 0.0
        out.append(FreeAgentRank(p, model.value(p), week, adds, bool(adds) and 0 <= p.percent_owned < BREAKOUT_MAX_OWNED,
                                 tuple(t[0] for t in p.tags), max(p.edge, key=lambda a: abs(a['delta']))['reason'] if p.edge else ""))
    return out


def _week_total(roster: list[PlayerInfo], starters) -> tuple[float, dict]:
    best = best_lineup(roster, starters)
    return sum(availability(p) for p in best.values() if p), best


def _ros_best(model: ValueModel, roster: list[PlayerInfo]):
    score = lambda p: model.ppg(p) * (model.ros_points(p) / max(model.ppg(p) * model.games_left(p), 1e-9))
    best = best_lineup(roster, model.starters, value=score, eligible=lambda p: True)
    return best, sum(model.ros_points(p) for p in best.values() if p)


def suggest_add_drops(snap: LeagueSnapshot, model: ValueModel, fas: list[PlayerInfo],
                      sleeper_index: Optional[SleeperIndex] = None, trending: Optional[dict[str, int]] = None,
                      max_suggestions: int = 8, pool_size: int = 30, drops_per_add: int = 5) -> list[AddDrop]:
    me = snap.my_team.roster
    ranks = rank_free_agents(model, fas, sleeper_index, trending)
    by_id = {r.player.player_id: r for r in ranks}
    # candidates: best by ROS value, best this week, and anything trending
    shortlist: dict[int, PlayerInfo] = {}
    for key in (lambda r: r.ros_value, lambda r: r.week_value, lambda r: r.trending_adds):
        for r in sorted(ranks, key=key, reverse=True)[:pool_size // 2]:
            shortlist[r.player.player_id] = r.player

    week0, _ = _week_total(me, snap.starters if hasattr(snap, "starters") else snap.starter_slots)
    ros_best0, ros0 = _ros_best(model, me)
    keep_ids = {p.player_id for p in ros_best0.values() if p}
    droppable = sorted((p for p in me if p.player_id not in keep_ids), key=model.ros_points)[:drops_per_add]
    if not droppable:
        return []

    results: list[AddDrop] = []
    for fa in shortlist.values():
        best: Optional[AddDrop] = None
        for drop in droppable:
            new = [p for p in me if p.player_id != drop.player_id] + [fa]
            week1, wk_best = _week_total(new, snap.starter_slots)
            ros_best1, ros1 = _ros_best(model, new)
            weekly, ros_gain = week1 - week0, ros1 - ros0
            depth = max(0.0, model.ros_points(fa) - model.ros_points(drop)) * DEPTH_WEIGHT
            score = ros_gain + weekly + depth
            if best is None or score > best.score:
                gl = max(model.games_left(fa), 1)
                best = AddDrop(fa, drop, round(weekly, 1), round(ros_gain, 1), round(ros_gain / gl, 1), round(score, 1),
                               _reason(fa, drop, me, ros_best1, wk_best, weekly),
                               by_id[fa.player_id].trending_adds)
        if best and best.score >= MIN_SCORE:
            results.append(best)
    results.sort(key=lambda r: -r.score)
    picked, per_pos = [], {}
    for r in results:                      # diversity: at most 2 suggestions per position
        if per_pos.get(r.add.position, 0) < MAX_PER_POSITION:
            per_pos[r.add.position] = per_pos.get(r.add.position, 0) + 1
            picked.append(r)
    return picked[:max_suggestions]


def _reason(fa, drop, me, ros_best_new, week_best_new, weekly) -> str:
    base = _reason_core(fa, drop, me, ros_best_new, week_best_new, weekly)
    if fa.edge:                                   # lead with WHY the edge engine likes him (e.g. "RB1 out -> he's next up")
        top = max(fa.edge, key=lambda a: abs(a["delta"]))
        return f"Edge: {top['reason']} {base}"
    if fa.tags:
        base = f"Tagged '{fa.tags[0][0]}'. {base}"
    if fa.context:                                 # e.g. "RB1 on IR, he's next up" - shown, but not counted in his projection
        return f"Context (not counted in the numbers): {fa.context[0]['text']} {base}"
    return base


def _reason_core(fa, drop, me, ros_best_new, week_best_new, weekly) -> str:
    starts_ros = any(p and p.player_id == fa.player_id for p in ros_best_new.values())
    starts_now = any(p and p.player_id == fa.player_id for p in week_best_new.values())
    starter_trouble = [p for p in me if p.position == fa.position and p.lineup_slot not in ("BE", "IR")
                       and (p.on_bye or p.is_out)]
    if starter_trouble and starts_now:
        t = starter_trouble[0]
        why = "is on a bye" if t.on_bye else "is injured"
        return f"{t.name} {why} this week; {fa.name} projects {weekly:+.1f} pts more than your best current option."
    if starts_ros:
        return f"Would earn a starting spot on your team for the rest of the season; {drop.name} is your least useful bench piece."
    if starts_now:
        return f"Better than your current options this week (+{weekly:.1f} pts)."
    return f"Bench upgrade over {drop.name}; no lineup change today but better injury/bye insurance."
