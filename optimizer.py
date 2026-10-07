"""Lineup optimizer: best starting lineup from this week's projections, injury/bye aware.

Slots come from the league settings (never assumed). Eligibility comes from ESPN's own
per-player `eligible_slots`. Solved as a max-weight assignment (Hungarian algorithm) so
overlapping slots (FLEX, OP, RB/WR, WR/TE) are handled optimally, not greedily.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from models import PlayerInfo

# Multipliers applied to ESPN's projection for players who might not play.
# OUT / bye players are excluded outright. Edit here if you disagree.
RISK_MULTIPLIER = {"QUESTIONABLE": 0.92, "DOUBTFUL": 0.5}

_BIG = 1e6


def availability(p: PlayerInfo) -> float:
    """Risk-adjusted projection for the current week (0 when they cannot play)."""
    if p.is_out or p.on_bye or p.lineup_slot == "IR":
        return 0.0
    return p.week_proj * RISK_MULTIPLIER.get(p.injury_status, 1.0)


def can_start(p: PlayerInfo) -> bool:
    return not (p.is_out or p.on_bye or p.lineup_slot == "IR")


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Min-cost assignment of n rows to m>=n columns. Returns column index per row."""
    n, m = len(cost), len(cost[0]) if cost else 0
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float("inf"), 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    result = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


def best_lineup(players: list[PlayerInfo], starter_slots: dict[str, int],
                value=availability, eligible=can_start) -> dict[int, Optional[PlayerInfo]]:
    """Return {slot_index: player or None}; slot_index follows expand_slots() order.
    `value` scores a player; `eligible` filters who may start (default: healthy, not on bye)."""
    slots = expand_slots(starter_slots)
    cands = [p for p in players if eligible(p)]
    n, m = len(slots), len(cands)
    if n == 0:
        return {}
    cost = []
    for slot in slots:
        row = [(-value(p) if slot in p.eligible_slots else _BIG) for p in cands]
        row += [_BIG - 1.0] * n          # dummy columns: "leave this slot empty"
        cost.append(row)
    cols = _hungarian(cost)
    out: dict[int, Optional[PlayerInfo]] = {}
    for i, c in enumerate(cols):
        out[i] = cands[c] if c < m and slots[i] in cands[c].eligible_slots else None
    return out


def expand_slots(starter_slots: dict[str, int]) -> list[str]:
    return [s for s, n in starter_slots.items() for _ in range(n)]


@dataclass
class Swap:
    player_in: PlayerInfo
    player_out: Optional[PlayerInfo]
    slot: str
    gain: float
    reason: str
    from_edge: bool = False        # True when this swap would NOT be recommended using ESPN's raw projections
    espn_gain: float = 0.0         # what the same swap is worth on ESPN's raw projections
    edge_note: str = ""

    def action(self) -> str:
        out = self.player_out.name if self.player_out else "(empty slot)"
        return f"In the ESPN app: bench {out} and start {self.player_in.name} at {self.slot}."


@dataclass
class LineupPlan:
    current: list[tuple[str, Optional[PlayerInfo]]]
    optimal: list[tuple[str, Optional[PlayerInfo]]]
    current_total: float
    optimal_total: float
    espn_current_total: float = 0.0
    espn_optimal_total: float = 0.0
    swaps: list[Swap] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def gain(self) -> float:
        return self.optimal_total - self.current_total


def current_lineup(players: list[PlayerInfo], starter_slots: dict[str, int]) -> list[tuple[str, Optional[PlayerInfo]]]:
    by_slot: dict[str, list[PlayerInfo]] = {}
    for p in players:
        if p.lineup_slot not in ("BE", "IR", "FA"):
            by_slot.setdefault(p.lineup_slot, []).append(p)
    rows = []
    for slot, n in starter_slots.items():
        mine = sorted(by_slot.get(slot, []), key=lambda p: -p.week_proj)
        rows += [(slot, mine[i] if i < len(mine) else None) for i in range(n)]
    return rows


def lineup_value(rows, value=availability) -> float:
    return sum(value(p) for _, p in rows if p)


def _reason(pin: PlayerInfo, pout: Optional[PlayerInfo]) -> str:
    if pout is None:
        return f"{pin.name} fills an empty slot."
    if pout.on_bye:
        return f"{pout.name} is on a bye this week."
    if pout.is_out:
        return f"{pout.name} is out ({pout.injury_status.replace('_', ' ').title()})."
    if pout.is_risky:
        return f"{pout.name} is {pout.injury_status.title()}; {pin.name} projects higher."
    return f"{pin.name} projects {availability(pin) - availability(pout):.1f} more points than {pout.name}."


def _plan_core(players: list[PlayerInfo], starter_slots: dict[str, int]) -> LineupPlan:
    slots = expand_slots(starter_slots)
    best = best_lineup(players, starter_slots)
    optimal = [(slots[i], best[i]) for i in range(len(slots))]
    current = current_lineup(players, starter_slots)

    cur_ids = {p.player_id for _, p in current if p}
    opt_ids = {p.player_id for _, p in optimal if p}
    ins = [p for _, p in optimal if p and p.player_id not in cur_ids]
    outs = [p for _, p in current if p and p.player_id not in opt_ids]
    slot_of = {p.player_id: s for s, p in optimal if p}

    swaps: list[Swap] = []
    ins.sort(key=lambda p: -availability(p))
    outs_left = list(outs)
    for pin in ins:
        # pair with an outgoing player of the same position first, else the weakest leftover
        same = [o for o in outs_left if o.position == pin.position]
        pool = same or outs_left
        pout = min(pool, key=availability) if pool else None
        if pout:
            outs_left.remove(pout)
        gain = availability(pin) - (availability(pout) if pout else 0.0)
        swaps.append(Swap(pin, pout, slot_of[pin.player_id], round(gain, 1), _reason(pin, pout)))
    # drop pure ties (equal projections) so the UI never recommends a +0.0 swap; keep forced moves (bye/out/empty slot)
    swaps = [s for s in swaps if s.gain >= 0.1 or s.player_out is None or s.player_out.is_out or s.player_out.on_bye]
    swaps.sort(key=lambda s: -s.gain)

    warnings = []
    for slot, p in optimal:
        if p and p.is_risky:
            warnings.append(f"{p.name} ({slot}) is {p.injury_status.title()} - check status before kickoff; have a backup ready.")
    for slot, p in optimal:
        if p is None:
            warnings.append(f"No healthy, non-bye player available for your {slot} slot.")
    return LineupPlan(current, optimal, round(lineup_value(current), 1), round(lineup_value(optimal), 1), swaps=swaps, warnings=warnings)


def plan_lineup(players: list[PlayerInfo], starter_slots: dict[str, int]) -> LineupPlan:
    """Optimal lineup on the (possibly edge-adjusted) projections, with each swap labeled 'from an edge' or not by comparing it
    to the plan you'd get from ESPN's raw numbers."""
    plan = _plan_core(players, starter_slots)
    if not any(p.has_edge for p in players):
        plan.espn_current_total, plan.espn_optimal_total = plan.current_total, plan.optimal_total
        return plan
    import dataclasses
    raw = [dataclasses.replace(p, week_proj=p.espn_week_proj or p.week_proj, edge=[], edge_ros=0.0) for p in players]
    base = _plan_core(raw, starter_slots)
    plan.espn_current_total, plan.espn_optimal_total = base.current_total, base.optimal_total
    espn_pairs = {(s.player_in.player_id, s.player_out.player_id if s.player_out else None): s.gain for s in base.swaps}
    for s in plan.swaps:
        key = (s.player_in.player_id, s.player_out.player_id if s.player_out else None)
        s.espn_gain = espn_pairs.get(key, 0.0)
        s.from_edge = key not in espn_pairs or (s.gain - s.espn_gain) >= 1.0 and s.espn_gain < 0.5
        if s.from_edge:
            top = max(s.player_in.edge or s.player_out.edge if s.player_out else s.player_in.edge, key=lambda a: abs(a["delta"]), default=None) if (s.player_in.edge or (s.player_out and s.player_out.edge)) else None
            s.edge_note = (f"Edge: {top['reason']}" if top else "Edge-adjusted projections change this call.")
    return plan
