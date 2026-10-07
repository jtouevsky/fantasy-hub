"""Trade engine v2.

Two questions, never blended:
  1. Should I offer it?    -> MY value: change in my optimal starting-lineup points, week by week, rest of season (season.py).
  2. Would they accept it? -> THEIR perception: MARKET value + need + situation + history (market.py, acceptance.py).

Search is "cheapest winning offer first": for every player I might want (any team in the league), find the smallest package I can give that
still clears the acceptance threshold, preferring 1-for-1 over 2-for-1 over 1-for-2 over 2-for-2, and never adding a sweetener the model doesn't need.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Optional

import acceptance as acc
from market import Market, soft
from models import LeagueSnapshot, PlayerInfo, TeamInfo
from season import Season
from strategy import Strategy

TRADEABLE = ("QB", "RB", "WR", "TE")
GOOD_FOR_ME = 10.0            # weighted rest-of-season lineup points that make a trade clearly good for me
MIN_TARGET_GAIN = 6.0         # a player I'd want must add at least this much to my lineup if he came for free
R_FLOOR = 0.36                # their market share below this can't clear acceptance: skip without an exact evaluation
SPECULATIVE_GAP = 0.45        # model value this far above the market value (as a share of market value) is flagged speculative
MAX_EXACT_PER_TARGET = 6
SKILL_PAIR_POOL = 10


@dataclass
class Constraints:
    partner: Optional[int] = None                    # team_id; None = scan the whole league
    offering: list[int] = field(default_factory=list)  # ids I want to move (the core of the give)
    get_ids: list[int] = field(default_factory=list)   # ids I specifically want
    want_positions: set[str] = field(default_factory=set)
    exclude_give_positions: set[str] = field(default_factory=set)
    exclude_give_ids: set[int] = field(default_factory=set)
    need_position: str = ""                          # e.g. "WR": the incoming player must help my lineup there (esp. playoffs)
    target_split: float = 60.0                       # MY-value share I'd like (60 = slightly in my favor)
    allow_loss: bool = False                         # explicit sell / rebuild move: lineup may get worse now
    max_results: int = 8
    notes: list[str] = field(default_factory=list)   # how the text was parsed

    def summary(self) -> list[str]:
        out = []
        if self.partner is not None:
            out.append(f"partner team #{self.partner}")
        if self.offering:
            out.append(f"offering {len(self.offering)} named player(s)")
        if self.get_ids:
            out.append(f"targeting {len(self.get_ids)} named player(s)")
        if self.want_positions:
            out.append("asking for " + "/".join(sorted(self.want_positions)))
        if self.exclude_give_positions:
            out.append("not giving " + "/".join(sorted(self.exclude_give_positions)))
        if self.need_position:
            out.append(f"must help my {self.need_position} slot (playoffs weighted)")
        out.append(f"target split ~{self.target_split:.0f}/{100 - self.target_split:.0f} in my value, near-even in market value")
        if self.allow_loss:
            out.append("sell/rebuild: lineup may dip")
        return out


@dataclass
class LadderStep:
    name: str                                        # Open / Fair / Walk away
    give: list[PlayerInfo]
    acceptance: str
    my_delta: float
    market_share_theirs: float
    note: str = ""


@dataclass
class TradeEval:
    other: TeamInfo
    give: list[PlayerInfo]
    get: list[PlayerInfo]
    my_delta: float                                  # weighted rest-of-season starting-lineup points gained (negative = loses)
    my_avg_week: float
    my_weeks: list[tuple[int, float, float]]         # (week, before, after)
    my_get_value: float
    my_give_value: float
    my_split: float                                  # % of the combined MY-value I receive (smooth, never clipped)
    market_get: float
    market_give: float
    their_delta: float
    their_avg_week: float
    their_weeks: list[tuple[int, float, float]]
    acceptance: acc.Acceptance
    my_drop: Optional[PlayerInfo] = None             # who I'd have to cut if I receive more players than I send
    their_drop: Optional[PlayerInfo] = None
    sweetener: list[PlayerInfo] = field(default_factory=list)   # extras the acceptance model needed
    ladder: list[LadderStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    score: float = 0.0
    speculative: bool = False                        # my model is far more bullish than the consensus on someone I'd receive

    @property
    def kind(self) -> str:
        return f"{len(self.give)}-for-{len(self.get)}"

    @property
    def verdict_me(self) -> str:
        return "good" if self.my_delta >= GOOD_FOR_ME else "marginal" if self.my_delta >= 0 else "no"

    @property
    def verdict_me_text(self) -> str:
        return {"good": "Good for you", "marginal": "Marginal for you", "no": "Not good for you"}[self.verdict_me]

    @property
    def market_split_theirs(self) -> float:
        return 100 * self.acceptance.market_share_theirs


class TradeWorld:
    """Everything the engine needs, computed once per data refresh."""

    def __init__(self, snap: LeagueSnapshot, season: Season, market: Market, strategy: Strategy, activity: list[dict] = (), db_path: Optional[str] = None):
        self.snap, self.season, self.market, self.strategy, self.db_path = snap, season, market, strategy, db_path
        self.me = snap.my_team
        self.stats = acc.manager_stats(list(activity))
        self.negs = acc.negotiations(db_path) if db_path else []
        self._before: dict[int, dict] = {}

    def before(self, team: TeamInfo) -> dict:
        if team.team_id not in self._before:
            self._before[team.team_id] = self.season.season_lineup(team.roster)
        return self._before[team.team_id]

    def players(self) -> dict[int, PlayerInfo]:
        return {p.player_id: p for t in self.snap.teams for p in t.roster}


# ------------------------------------------------------------------------------------------------------------------
def _after_roster(world: TradeWorld, roster: list[PlayerInfo], out: list[PlayerInfo], inc: list[PlayerInfo]) -> tuple[list[PlayerInfo], Optional[PlayerInfo]]:
    """Roster after the swap. If it no longer fits, the worst droppable player goes (never someone in an IR slot, never a player just acquired)."""
    out_ids = {p.player_id for p in out}
    new = [p for p in roster if p.player_id not in out_ids] + [_as_bench(p) for p in inc]
    drop = None
    if world.season.roster_count(new) > world.season.capacity:
        drop = world.season.worst_droppable(new, protect={p.player_id for p in inc})
        if drop is not None:
            new = [p for p in new if p.player_id != drop.player_id]
    return new, drop


def _as_bench(p: PlayerInfo) -> PlayerInfo:
    return p                                                                      # slot labels don't matter to the lineup solver


def evaluate(world: TradeWorld, other: TeamInfo, give: list[PlayerInfo], get: list[PlayerInfo], sweetener: Optional[list[PlayerInfo]] = None) -> TradeEval:
    s, m = world.season, world.market
    me = world.me
    my_after, my_drop = _after_roster(world, me.roster, give, get)
    th_after, th_drop = _after_roster(world, other.roster, get, give)
    mb, tb = world.before(me), world.before(other)
    ma, ta = s.season_lineup(my_after), s.season_lineup(th_after)
    my_weeks = [(w, b, a) for (w, b), (_, a) in zip(mb["weeks"], ma["weeks"])]
    th_weeks = [(w, b, a) for (w, b), (_, a) in zip(tb["weeks"], ta["weeks"])]
    my_delta, th_delta = ma["total"] - mb["total"], ta["total"] - tb["total"]
    nweeks = max(len(s.weeks), 1)
    gv, vv = sum(soft(s.par(p)) for p in get), sum(soft(s.par(p)) for p in give)
    depth_unused = all(tb["starts"].get(p.player_id, 0) == 0 for p in get)
    their_ppg = th_delta / sum(s.weights.values())
    a = acc.assess(m, s, other, give, get, their_ppg, depth_unused, world.stats, world.negs, th_after)
    ev = TradeEval(other, list(give), list(get), my_delta, my_delta / sum(s.weights.values()), my_weeks, gv, vv, 100 * gv / (gv + vv) if gv + vv else 50.0,
                   m.package(get), m.package(give), th_delta, their_ppg, th_weeks, a, my_drop, th_drop, list(sweetener or []))
    if my_drop:
        ev.notes.append(f"You'd have to cut {my_drop.name} to fit this (your least useful non-IR player).")
    if th_drop:
        ev.notes.append(f"{other.owner_label.split()[0] if other.owner_label else other.name} would have to cut {th_drop.name}; that cost is included in his side.")
    for p in get:
        edge = soft(s.healthy_par(p)) - soft(m.value(p))
        if m.row(p).has_market and edge > SPECULATIVE_GAP * max(soft(m.value(p)), 10.0):
            ev.speculative = True
            ev.notes.append(f"Speculative: my model is far more bullish on {p.name} than the consensus is; treat the gain as a hunch, not a sure thing.")
    for p in give:
        if p.lineup_slot == "IR":
            ev.notes.append(f"{p.name} is in an IR slot, so moving him frees no bench spot for you.")
    for p in get:
        for tag, _ in p.tags:
            if tag == "buy low":
                ev.notes.append(f"{p.name} is tagged BUY LOW (opportunity > production lately).")
            elif tag == "sell high":
                ev.notes.append(f"{p.name} is tagged SELL HIGH (production > opportunity lately); expect a fade.")
    for p in give:
        for tag, _ in p.tags:
            if tag == "sell high":
                ev.notes.append(f"You're giving {p.name}, tagged SELL HIGH: good timing to move him.")
            elif tag == "buy low":
                ev.notes.append(f"You're giving {p.name}, tagged BUY LOW: you may be selling at the bottom.")
    return ev


def _score(ev: TradeEval, c: Constraints) -> float:
    bonus = {"likely": 3.0, "coin flip": 0.0, "unlikely": -8.0}[ev.acceptance.label]
    return ev.my_delta - 0.4 * abs(ev.my_split - c.target_split) + bonus


# ------------------------------------------------------------------------------------------------------------------
def _my_pool(world: TradeWorld, c: Constraints) -> list[PlayerInfo]:
    return [p for p in world.me.roster if p.position in TRADEABLE and p.player_id not in c.exclude_give_ids and p.position not in c.exclude_give_positions]


def _wanted(world: TradeWorld, other: TeamInfo, c: Constraints) -> list[PlayerInfo]:
    """Players on `other` I'd want even if they came free (they'd raise my weighted lineup total), best first."""
    s = world.season
    base = world.before(world.me)["total"]
    out = []
    for p in other.roster:
        if p.position not in TRADEABLE or (c.want_positions and p.position not in c.want_positions) or (c.get_ids and p.player_id not in c.get_ids):
            continue
        gain = s.season_lineup(world.me.roster + [p])["total"] - base
        if gain >= MIN_TARGET_GAIN or p.player_id in c.get_ids:
            out.append((gain, p))
    return [p for _, p in sorted(out, key=lambda x: -x[0])]


def _give_options(world: TradeWorld, c: Constraints, core: list[PlayerInfo], pool: list[PlayerInfo]) -> list[list[PlayerInfo]]:
    """Candidate give sets, smallest first: the core alone, then core + 1 extra, then core + 2 extras (never anything the search doesn't try in this order)."""
    m = world.market
    core_ids = {p.player_id for p in core}
    extras = sorted((p for p in pool if p.player_id not in core_ids), key=lambda p: m.worth(m.value(p)))
    top = sorted(extras, key=lambda p: -m.value(p))[:SKILL_PAIR_POOL]
    opts: list[list[PlayerInfo]] = [list(core)] if core else []
    opts += [list(core) + [x] for x in extras]
    if len(core) + 2 <= 2 or core:
        opts += [list(core) + [a, b] for a, b in itertools.combinations(top, 2) if len(core) + 2 <= 3]
    return sorted(opts, key=lambda g: (len(g), m.package(g)))


def _passes(ev: TradeEval, c: Constraints, world: TradeWorld) -> bool:
    if not ev.acceptance.plausible:
        return False
    if not c.allow_loss and (ev.my_delta < 0 or ev.my_avg_week < -0.01):
        return False
    if c.need_position:
        w_play = [w for w in world.season.weights if w > world.snap.reg_season_weeks]
        if not any(p.position == c.need_position for p in ev.get):
            return False
    return True


def search(world: TradeWorld, c: Optional[Constraints] = None) -> list[TradeEval]:
    """Whole-league scan (or one partner). Returns the best distinct trades, each with an offer ladder."""
    c = c or Constraints()
    me, mk = world.me, world.market
    partners = [t for t in world.snap.teams if t.team_id != me.team_id and (c.partner is None or t.team_id == c.partner)]
    pool = _my_pool(world, c)
    byid = world.players()
    core = [byid[i] for i in c.offering if i in byid and byid[i].owner_team_id == me.team_id] if c.offering else []
    results: list[TradeEval] = []
    for other in partners:
        wanted = _wanted(world, other, c)[:8]
        targets: list[list[PlayerInfo]] = [[p] for p in wanted]
        if not c.get_ids or len(c.get_ids) > 1:
            targets += [list(pair) for pair in itertools.combinations(wanted[:5], 2)]
        for T in targets:
            tried = 0
            best_size = None
            for G in _give_options(world, c, core, pool):
                if best_size is not None and len(G) > best_size:
                    break                                                         # a smaller offer already cleared: never add more
                recv = mk.package(G)
                r = recv / (recv + mk.package(T))
                if r < R_FLOOR:
                    continue
                tried += 1
                ev = evaluate(world, other, G, T, sweetener=[p for p in G if p.player_id not in {x.player_id for x in core}])
                if _passes(ev, c, world):
                    ev.score = _score(ev, c)
                    results.append(ev)
                    best_size = len(G)
                    break
                if tried >= MAX_EXACT_PER_TARGET:
                    break
    results.sort(key=lambda e: -e.score)
    seen, out = set(), []
    for ev in results:                                                           # one result per target set (the cheapest winning offer is already first)
        key = (ev.other.team_id, frozenset(p.player_id for p in ev.get))
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    out = out[:c.max_results]
    for ev in out:
        ev.ladder = build_ladder(world, ev, c, pool, core)
    return out


def build_ladder(world: TradeWorld, ev: TradeEval, c: Constraints, pool: list[PlayerInfo], core: list[PlayerInfo]) -> list[LadderStep]:
    """Open (cheapest offer that is still plausible) / Fair (market-even from his side) / Walk away (most I'd give and still gain)."""
    mk = world.market
    other, T = ev.other, ev.get
    options = _give_options(world, c, core, pool)
    cand = []
    for G in options:
        recv = mk.package(G)
        cand.append((recv / (recv + mk.package(T)), recv, G))
    steps: list[LadderStep] = []

    def step(name: str, G: list[PlayerInfo], note: str = "") -> Optional[LadderStep]:
        e = evaluate(world, other, G, T)
        return LadderStep(name, G, e.acceptance.label, e.my_delta, e.acceptance.market_share_theirs, note)

    open_ = LadderStep("Open", ev.give, ev.acceptance.label, ev.my_delta, ev.acceptance.market_share_theirs, "the least you can give that still looks plausible to him")
    steps.append(open_)
    fair_pool = [x for x in cand if x[1] >= mk.package(ev.give) - 1e-9]
    if fair_pool:
        r, _, G = min(fair_pool, key=lambda x: abs(x[0] - 0.5))
        if {p.player_id for p in G} != {p.player_id for p in ev.give}:
            steps.append(step("Fair", G, "market-even from his side"))
    gainers = []
    for r, recv, G in sorted(cand, key=lambda x: -x[1]):
        if recv <= mk.package(ev.give) + 1e-9:
            break
        quick = sum(world.season.par(p) for p in T) - sum(world.season.par(p) for p in G)
        if quick > 0:
            gainers.append(G)
        if len(gainers) >= 4:
            break
    for G in gainers:
        e = evaluate(world, other, G, T)
        if e.my_delta >= 2.0:
            steps.append(LadderStep("Walk away", G, e.acceptance.label, e.my_delta, e.acceptance.market_share_theirs, "the most I'd give: past this the deal stops paying off for you"))
            break
    seen, uniq = set(), []
    for st in steps:
        k = frozenset(p.player_id for p in st.give)
        if k not in seen:
            seen.add(k)
            uniq.append(st)
    return uniq


# ------------------------------------------------------------------------------------------------------------------
_SPLIT = re.compile(r"(\d{2})\s*/\s*(\d{2})")
_POS_WORDS = {"receiver": "WR", "receivers": "WR", "wr": "WR", "wide receiver": "WR", "running back": "RB", "rb": "RB", "back": "RB", "tight end": "TE", "te": "TE", "quarterback": "QB", "qb": "QB"}


def parse_request(text: str, world: TradeWorld) -> Constraints:
    """Rule-based parse of a plain-English trade request into explicit constraints (shown to the user so they can be corrected)."""
    c = Constraints()
    t = " " + text.lower() + " "
    byid = world.players()
    names = {p.name.lower(): p for p in byid.values()}
    mine = {p.name.lower(): p for p in world.me.roster}

    def find_player(token: str, roster: Optional[dict] = None) -> Optional[PlayerInfo]:
        pool = roster if roster is not None else names
        last = {n.split()[-1].rstrip(".").lower(): p for n, p in pool.items()}
        for n, p in pool.items():
            if n in t:
                return p
        for l, p in last.items():
            if re.search(rf"\b{re.escape(l)}\b", token) and len(l) > 3:
                return p
        return None

    m = _SPLIT.search(t)
    if m:
        c.target_split = max(50.0, min(float(m.group(1)), 80.0))
        c.notes.append(f"split {m.group(1)}/{m.group(2)}")
    elif "slightly in my favor" in t or "slight edge" in t:
        c.target_split, _ = 60.0, c.notes.append("'slightly in my favor' -> 60/40")
    elif "heavily in my favor" in t or "big win" in t:
        c.target_split, _ = 70.0, c.notes.append("'heavily in my favor' -> 70/30")
    elif "fair" in t or "even" in t:
        c.target_split, _ = 52.0, c.notes.append("'fair/even' -> ~52/48")
    for team in world.snap.teams:
        if team.team_id == world.me.team_id:
            continue
        keys = [team.name.lower()] + [o.first_name.lower() for o in team.owners if o.first_name] + [o.last_name.lower() for o in team.owners if o.last_name]
        if any(re.search(rf"\b{re.escape(k)}\b", t) for k in keys if len(k) > 2):
            c.partner = team.team_id
            c.notes.append(f"partner: {team.name}")
            break
    for pos_phrase in sorted(_POS_WORDS, key=len, reverse=True):
        if re.search(rf"\b(?:don'?t|do not|no|not|without)\b[^.]*\b(?:give up|trade|move|include)\b[^.]*\b{re.escape(pos_phrase)}s?\b", t):
            c.exclude_give_positions.add(_POS_WORDS[pos_phrase])
            c.notes.append(f"won't give {_POS_WORDS[pos_phrase]}s")
    need = re.search(r"need (?:a |an )?(wr|rb|te|qb|receiver|running back|tight end|quarterback)\s*(\d)?", t)
    if need:
        c.need_position = _POS_WORDS[need.group(1)]
        c.notes.append(f"needs a {c.need_position}" + (" for the playoffs" if "playoff" in t else ""))
    if "sell high" in t or "sell " in t or "rebuild" in t:
        sell = re.search(r"sell(?: high)?(?: on)? ([a-z.' ]+?)(?: to|,|\.| for| and|$)", t)
        if sell:
            p = find_player(sell.group(1), mine)
            if p:
                c.offering = [p.player_id]
                c.notes.append(f"selling {p.name}")
        c.allow_loss = c.allow_loss or "rebuild" in t
    if not c.offering:
        for kw in ("for my ", "trade my ", "offer my ", "offering my ", "give up my ", "my "):
            idx = t.find(kw)
            if idx >= 0:
                p = find_player(t[idx + len(kw): idx + len(kw) + 28], mine)
                if p:
                    c.offering = [p.player_id]
                    c.notes.append(f"offering {p.name}")
                    break
    for phrase, pos in _POS_WORDS.items():
        if re.search(rf"\b(?:get|want|need|receive|acquire)\b[^.]*\b(?:one of his |his |a |an |some )?{re.escape(phrase)}s?\b", t) and not (need and pos == c.need_position):
            c.want_positions.add(pos)
    if c.want_positions:
        c.notes.append("asking for " + "/".join(sorted(c.want_positions)))
    return c


def pitch(world: TradeWorld, ev: TradeEval) -> str:
    """A short, casual message highlighting what THEY gain. Facts only (from the evaluation); never auto-sent."""
    first = (ev.other.owners[0].first_name if ev.other.owners and ev.other.owners[0].first_name else ev.other.name)
    give = " + ".join(p.name for p in ev.give)
    get = " + ".join(p.name for p in ev.get)
    pts = []
    if ev.their_avg_week >= 0.5:
        pts.append(f"it upgrades your lineup by about {ev.their_avg_week:.1f} pts/week over the rest of the year")
    gets_top = max(ev.give, key=lambda p: world.market.value(p))
    a = ev.acceptance
    if a.market_share_theirs >= 0.5:
        pts.append(f"by the consensus rankings you're getting the more valuable player ({gets_top.name} is ranked higher than what you're giving up)")
    for p in ev.give:
        if p.lineup_slot == "IR" and p.market.get("ros_pos_rank"):
            pts.append(f"{p.name} is a top-{int(p.market['ros_pos_rank'])+0} {p.position} on the consensus rest-of-season board and is expected back around week {world.season.week + round(world.season.timeline(p).expected_games_out)}")
    if not pts:
        pts.append("it's pretty even on the consensus rankings, and I'm happy to talk about tweaks")
    return f"Hey {first}, how about {give} for {get}? " + "; ".join(pts[:3]).capitalize() + ". Let me know what you think!"


def make_world(snap: LeagueSnapshot, fas: list[PlayerInfo], model, strategy: Strategy, market_signals: dict[int, dict], activity: list[dict] = (),
               db_path: Optional[str] = None) -> TradeWorld:
    """Attach ESPN market signals to every player, then build the season model, market and trade world."""
    everyone = [p for t in snap.teams for p in t.roster] + list(fas)
    for p in everyone:
        p.market = market_signals.get(p.player_id, p.market)
    season = Season(snap, model, strategy, fas)
    return TradeWorld(snap, season, Market(season, everyone), strategy, activity, db_path)


# ------------------------------------------------------------------------------------------------------------------
def _pl(p: PlayerInfo, world: TradeWorld) -> dict:
    s = world.season
    d = {"name": p.name, "position": p.position, "nfl_team": p.pro_team, "lineup_slot": p.lineup_slot, "injury_status": p.injury_status,
         "projected_points_this_week": round(p.week_proj, 1), "expected_points_rest_of_season": round(s.raw_ros(p)),
         "market_value": round(world.market.value(p), 1), "my_value": round(s.par(p), 1)}
    if p.injury_status in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
        d["injury_outlook"] = s.timeline(p).note
    return d


def risk_lines(world: TradeWorld, ev: TradeEval) -> list[str]:
    out = []
    for p in ev.get:
        if p.injury_status in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
            out.append(f"{p.name}: {world.season.timeline(p).note}")
        if p.games_played and p.games_played < 3:
            out.append(f"{p.name} has only {p.games_played} games played this year; his production estimate is thin.")
    if ev.speculative:
        out.append("Part of the gain rests on my model being more bullish than the consensus; treat it as a hunch.")
    return out


def explain(world: TradeWorld, ev: TradeEval) -> dict:
    """Plain-language answer to the two separate questions, plus risk and the offer ladder."""
    a = ev.acceptance
    me_txt = (f"Over the rest of the season this changes your weekly lineup by {ev.my_avg_week:+.1f} pts on average "
              f"({ev.my_delta:+.0f} weighted points, playoffs count 1.5x).")
    mkt_txt = (f"By market value he gets {ev.market_split_theirs:.0f}% of what changes hands. " + ("; ".join(a.reasons[:3]) if a.reasons else ""))
    return {"should_i_offer": {"verdict": ev.verdict_me_text, "detail": me_txt, "my_value_split": f"{ev.my_split:.0f}/{100 - ev.my_split:.0f}"},
            "would_they_accept": {"label": a.label, "detail": mkt_txt, "market_value_split_for_them": f"{ev.market_split_theirs:.0f}/{100 - ev.market_split_theirs:.0f}",
                                  "signals": [{"name": x.name, "effect": round(x.contribution, 2), "why": x.text} for x in a.signals],
                                  "confirmed_by_manager": a.confirmed},
            "risk": risk_lines(world, ev)}


def describe(world: TradeWorld, ev: TradeEval) -> dict:
    ex = explain(world, ev)
    return {"type": ev.kind, "other_team": ev.other.name, "i_give": [_pl(p, world) for p in ev.give], "i_get": [_pl(p, world) for p in ev.get],
            **ex, "my_lineup_change_per_week": round(ev.my_avg_week, 1), "their_lineup_change_per_week": round(ev.their_avg_week, 1),
            "week_by_week": [{"week": w, "before": round(b, 1), "after": round(a, 1)} for w, b, a in ev.my_weeks],
            "must_cut": ev.my_drop.name if ev.my_drop else None, "notes": ev.notes, "speculative": ev.speculative,
            "offer_ladder": [{"step": st.name, "give": [p.name for p in st.give], "would_they_accept": st.acceptance, "my_lineup_change": round(st.my_delta, 1), "note": st.note} for st in ev.ladder],
            "espn_action": f"Open {ev.other.name}'s team in the ESPN app and propose this trade."}
