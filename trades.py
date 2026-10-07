"""Trade evaluator and trade finder (read-only: it only *suggests*; you send the offer in the ESPN app).

Fairness uses the value model in valuation.py. Acceptability uses each side's lineup change, so a
trade that fills a hole on THEIR roster ranks higher than one that just wins on paper.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Optional

from models import LeagueSnapshot, PlayerInfo, TeamInfo
from optimizer import best_lineup
from valuation import ValueModel, fairness

# ---- finder scoring knobs (all in "score points"; see README) -----------------
SPLIT_MISS_PENALTY = 3.0        # per percentage point away from the target split
LOPSIDED_OVER = 65.0            # my share above this looks like a robbery to them...
LOPSIDED_PENALTY = 6.0          # ...penalty per point over
THEIR_LINEUP_BONUS = 4.0        # per weekly point their lineup improves (capped)
THEIR_LINEUP_PENALTY = 10.0    # per weekly point their lineup gets worse
MY_LINEUP_WEIGHT = 4.0          # per weekly point my lineup changes (capped both ways)
LINEUP_CAP = 4.0
PREFILTER_WINDOW = 20.0         # only lineup-score packages within +/- this many points of the target
UNLIKELY_PENALTY = 20.0         # extra penalty when the other manager would probably say no
MIN_MY_SHARE = 40.0             # never suggest trades where I lose badly on value


@dataclass
class LineupImpact:
    before_ppg: float
    after_ppg: float
    now_starting: list[str] = field(default_factory=list)      # players who enter the starting lineup
    no_longer_starting: list[str] = field(default_factory=list)
    pickups_needed: list[str] = field(default_factory=list)   # positions where a free waiver pickup must fill a hole

    @property
    def delta(self) -> float:
        return self.after_ppg - self.before_ppg


@dataclass
class TradeEval:
    give: list[PlayerInfo]
    get: list[PlayerInfo]
    value_get: float            # what I receive, in value-over-replacement points
    value_give: float
    my_share: float             # percent; 60 means I get 60% of the combined value
    their_share: float
    mine: LineupImpact
    theirs: LineupImpact
    other_team: str = ""
    score: float = 0.0
    acceptance: str = ""        # Likely / Maybe / Unlikely
    notes: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return f"{len(self.give)}-for-{len(self.get)}"


def _impact(model: ValueModel, roster: list[PlayerInfo], new_roster: list[PlayerInfo]) -> LineupImpact:
    before, after = model.starting_lineup(roster), model.starting_lineup(new_roster)
    real = lambda d: {i: p for i, p in d.items() if i > 0}
    phantoms = lambda d: sorted(p.position for i, p in d.items() if i < 0)
    extra = phantoms(after)
    for pos in phantoms(before):
        if pos in extra:
            extra.remove(pos)
    return LineupImpact(
        sum(model.eff_ppg(p) for p in before.values()), sum(model.eff_ppg(p) for p in after.values()),
        [p.name for i, p in real(after).items() if i not in before],
        [p.name for i, p in real(before).items() if i not in after],
        extra,
    )


def _acceptance(their_share: float, their_delta: float) -> str:
    if their_share < 35 or (their_delta < -1.5 and their_share < 45):
        return "Unlikely"
    if their_share >= 45 or (their_share >= 40 and their_delta > 0):
        return "Likely"
    return "Maybe"


def evaluate_trade(snap: LeagueSnapshot, model: ValueModel, other: TeamInfo,
                   give: list[PlayerInfo], get: list[PlayerInfo], me: Optional[TeamInfo] = None) -> TradeEval:
    """`give` = players I send, `get` = players I receive from `other`."""
    me = me or snap.my_team
    give_ids, get_ids = {p.player_id for p in give}, {p.player_id for p in get}
    my_ids = {p.player_id for p in me.roster}
    their_ids = {p.player_id for p in other.roster}
    if not give_ids <= my_ids:
        raise ValueError("You can only give players on your roster.")
    if not get_ids <= their_ids:
        raise ValueError(f"You can only ask for players on {other.name}.")

    v_get, v_give = model.package_value(get), model.package_value(give)
    mine_share, theirs_share = fairness(v_get, v_give)
    my_new = [p for p in me.roster if p.player_id not in give_ids] + list(get)
    their_new = [p for p in other.roster if p.player_id not in get_ids] + list(give)
    mine, theirs = _impact(model, me.roster, my_new), _impact(model, other.roster, their_new)

    ev = TradeEval(list(give), list(get), round(v_get, 1), round(v_give, 1), mine_share, theirs_share, mine, theirs,
                   other_team=other.name, acceptance=_acceptance(theirs_share, theirs.delta))
    if len(get) > len(give):
        drop = min((p for p in my_new if p.player_id not in get_ids), key=model.ros_points, default=None)
        ev.notes.append(f"You receive more players than you send, so you must drop someone"
                        + (f" (your weakest is {drop.name})." if drop else "."))
    if len(give) > len(get):
        ev.notes.append(f"{other.name} must drop a player to fit this trade.")
    ev.score = _score(ev)
    return ev


def _score(ev: TradeEval, target: float = 50.0) -> float:
    s = 100.0 - SPLIT_MISS_PENALTY * abs(ev.my_share - target)
    s += THEIR_LINEUP_BONUS * min(ev.theirs.delta, LINEUP_CAP) if ev.theirs.delta > 0 else THEIR_LINEUP_PENALTY * max(ev.theirs.delta, -LINEUP_CAP)
    s += MY_LINEUP_WEIGHT * max(-LINEUP_CAP, min(ev.mine.delta, LINEUP_CAP))
    if ev.my_share > LOPSIDED_OVER:
        s -= LOPSIDED_PENALTY * (ev.my_share - LOPSIDED_OVER)
    if ev.acceptance == "Unlikely":
        s -= UNLIKELY_PENALTY
    if len(ev.give) > len(ev.get):
        s -= 2.0           # they'd have to drop someone
    elif len(ev.get) > len(ev.give):
        s -= 1.0
    return round(s, 1)


def find_trades(snap: LeagueSnapshot, model: ValueModel, other: TeamInfo, offering: list[PlayerInfo],
                target_split: float = 60.0, want_positions: Optional[set[str]] = None,
                max_results: int = 10, me: Optional[TeamInfo] = None) -> list[TradeEval]:
    """Search 1-for-1, 2-for-1 and 1-for-2 packages that include everything in `offering`.

    target_split is MY share of the value (60 = slightly in my favor). `want_positions` limits what I ask for
    (e.g. {"WR"}); for 1-for-2 at least one requested player must match.
    """
    me = me or snap.my_team
    offer_ids = {p.player_id for p in offering}
    theirs = [p for p in other.roster if model.value(p) > 0 or model.ppg(p) > 0]
    wants = lambda p: not want_positions or p.position in want_positions
    my_extras = [p for p in me.roster if p.player_id not in offer_ids]

    packages: list[tuple[list[PlayerInfo], list[PlayerInfo]]] = []
    for g in theirs:
        if wants(g) and model.value(g) > 0:
            packages.append((list(offering), [g]))                              # N-for-1 with the offered players
            if len(offering) == 1:
                packages += [(list(offering) + [x], [g]) for x in my_extras]    # 2-for-1: I add a sweetener
    if len(offering) == 1:
        # second player may be a cheap lineup-filler (e.g. a TE to replace the one I'm sending)
        for a, b in itertools.combinations(theirs, 2):
            if (wants(a) and model.value(a) > 0) or (wants(b) and model.value(b) > 0):
                packages.append((list(offering), [a, b]))                       # 1-for-2

    scored: list[TradeEval] = []
    for give, get in packages:
        share, _ = fairness(model.package_value(get), model.package_value(give))
        if share < MIN_MY_SHARE or abs(share - target_split) > PREFILTER_WINDOW:
            continue
        ev = evaluate_trade(snap, model, other, give, get, me)
        ev.score = _score(ev, target_split)
        scored.append(ev)
    scored.sort(key=lambda e: -e.score)
    return scored[:max_results]


# ---------------------------------------------------------------------------
# Plain-English explanation
# ---------------------------------------------------------------------------
def _names(ps: list[PlayerInfo]) -> str:
    return " + ".join(f"{p.name} ({p.position}, {p.pro_team})" for p in ps)


def describe(ev: TradeEval, my_name: str = "you") -> str:
    lines = [
        f"**You give:** {_names(ev.give)}",
        f"**You get:** {_names(ev.get)} from {ev.other_team}",
        f"**Value split:** {ev.my_share:.0f}/{ev.their_share:.0f} "
        f"({'in your favor' if ev.my_share > 52 else 'in their favor' if ev.my_share < 48 else 'about even'}). "
        f"Chance they accept: {ev.acceptance}.",
    ]
    for label, imp in (("Your lineup", ev.mine), (f"{ev.other_team}'s lineup", ev.theirs)):
        change = f"{imp.delta:+.1f} pts/week"
        detail = ""
        if imp.now_starting:
            detail += f" {', '.join(imp.now_starting)} would start"
        if imp.no_longer_starting:
            detail += f"{';' if detail else ''} {', '.join(imp.no_longer_starting)} would move to the bench"
        if imp.pickups_needed:
            detail += f"{';' if detail else ''} would need a free {'/'.join(imp.pickups_needed)} pickup from waivers"
        lines.append(f"- {label}: {change}.{detail}")
    lines += [f"- Note: {n}" for n in ev.notes]
    lines.append(f"_To do this: in the ESPN app, open {ev.other_team}'s team and propose this trade._")
    return "\n".join(lines)
