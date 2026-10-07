"""Acceptance model: how likely is THIS manager to say yes? (never mixed with 'should I offer', which uses my value.)

Signals, each reported with its contribution (log-odds) and a plain-English reason:
  market fairness (their side)   largest factor; uses MARKET value with a consolidation premium and the roster spot they must clear
  need fit                       their weekly lineup change over the rest of the season; depth they don't use
  their situation                contender vs. out of the race, and whether the incoming player is hurt
  name value                     how much of a player's price is reputation rather than results (they overrate brand names)
  trade history                  has this manager actually made trades this season (ESPN activity feed)?
  negotiation history            Bayesian tendency from logged outcomes; exact logged answers override as "confirmed by manager"
The result is a label (likely / coin flip / unlikely) plus the top reasons. No fake-precise percentages: the sample is small.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Optional

import db
from market import Market, soft
from models import PlayerInfo, TeamInfo
from season import Season

BASE = -0.15
FAIR_CENTER = 0.47            # their share of market value at which the logit from fairness alone is 0
FAIR_SCALE = 14.0            # market fairness is the dominant signal: +-0.1 of market share moves the logit by 1.4
LIKELY, COIN = 0.5, -0.7
TAU2 = 1.0                    # prior variance of a manager's tendency offset (league-wide prior: centered on 0)
CLIP_TENDENCY = 1.5


@dataclass
class Signal:
    name: str
    contribution: float
    text: str


@dataclass
class Acceptance:
    label: str                                  # likely | coin flip | unlikely
    logit: float
    signals: list[Signal] = field(default_factory=list)
    confirmed: Optional[str] = None             # set when a logged negotiation decides it
    market_share_theirs: float = 0.5

    @property
    def reasons(self) -> list[str]:
        top = sorted(self.signals, key=lambda s: -abs(s.contribution))[:3]
        return ([self.confirmed] if self.confirmed else []) + [f"{s.name}: {s.text}" for s in top if abs(s.contribution) >= 0.1]

    @property
    def plausible(self) -> bool:
        return self.label in ("likely", "coin flip")


def label_for(logit: float) -> str:
    return "likely" if logit >= LIKELY else "coin flip" if logit >= COIN else "unlikely"


# ---- league activity -> manager stats ---------------------------------------------------------------------------
def manager_stats(activity: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for a in activity:
        tid = a.get("team_id")
        if tid is None:
            continue
        s = out.setdefault(tid, {"trade_ts": set(), "adds": 0, "drops": 0, "last_trade": 0.0})
        act = a.get("action", "")
        if act.startswith("TRADE"):
            s["trade_ts"].add(round(a["ts"], -2))                    # both sides of a trade share (about) one timestamp
            s["last_trade"] = max(s["last_trade"], a["ts"])
        elif "ADDED" in act:
            s["adds"] += 1
        elif act == "DROPPED":
            s["drops"] += 1
    for s in out.values():
        s["trades"] = len(s.pop("trade_ts"))
    return out


# ---- negotiation log ------------------------------------------------------------------------------------------
def log_negotiation(db_path, team_id: int, manager: str, give: list[PlayerInfo], get: list[PlayerInfo], response: str, note: str = "",
                    model_logit: Optional[float] = None) -> int:
    if response not in ("accepted", "rejected", "countered", "pending"):
        raise ValueError("response must be accepted, rejected, countered or pending")
    with db.connect(db_path) as c:
        cur = c.execute("INSERT INTO negotiations(ts, team_id, manager, give_ids, get_ids, give_names, get_names, response, note, model_logit) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), team_id, manager, json.dumps(sorted(p.player_id for p in give)), json.dumps(sorted(p.player_id for p in get)),
                         " + ".join(p.name for p in give), " + ".join(p.name for p in get), response, note, model_logit))
        return int(cur.lastrowid)


def negotiations(db_path, team_id: Optional[int] = None) -> list[dict]:
    with db.connect(db_path) as c:
        rows = c.execute("SELECT * FROM negotiations" + (" WHERE team_id=?" if team_id is not None else "") + " ORDER BY id DESC", (team_id,) if team_id is not None else ()).fetchall()
    return [{**dict(r), "give_ids": set(json.loads(r["give_ids"])), "get_ids": set(json.loads(r["get_ids"]))} for r in rows]


def update_negotiation(db_path, nid: int, response: str, note: Optional[str] = None) -> None:
    with db.connect(db_path) as c:
        c.execute("UPDATE negotiations SET response=?, note=COALESCE(?, note) WHERE id=?", (response, note, nid))


def tendency(negs: list[dict]) -> float:
    """Posterior-mean shift (log-odds) of how readily this manager accepts vs. what the model predicted.
    One Newton step of Bayesian logistic regression from 0 with a N(0, TAU2) league-wide prior: sum(y - p) / (sum p(1-p) + 1/TAU2).
    Few observations keep it near 0; consistent surprises move it."""
    obs = [(1.0 if n["response"] == "accepted" else 0.0 if n["response"] == "rejected" else 0.35 if n["response"] == "countered" else None, n["model_logit"]) for n in negs]
    obs = [(y, z) for y, z in obs if y is not None and z is not None]
    if not obs:
        return 0.0
    ps = [1.0 / (1.0 + math.exp(-z)) for _, z in obs]
    num = sum(y - p for (y, _), p in zip(obs, ps))
    den = sum(p * (1 - p) for p in ps) + 1.0 / TAU2
    return max(-CLIP_TENDENCY, min(CLIP_TENDENCY, num / den))


def confirmed_override(negs: list[dict], give_ids: set[int], get_ids: set[int]) -> Optional[tuple[str, str]]:
    """A logged answer that already decides this offer: (label, text). Only for the same ask or a strictly better/worse version of it."""
    for n in negs:                                        # newest first
        if n["response"] == "accepted" and get_ids <= n["get_ids"] and give_ids >= n["give_ids"] and get_ids:
            return "likely", f"Confirmed by manager: he said he'd do {n['give_names']} for {n['get_names']}" + (f" ({n['note']})" if n["note"] else "")
        if n["response"] == "rejected" and get_ids >= n["get_ids"] and give_ids <= n["give_ids"] and get_ids:
            return "unlikely", f"Confirmed by manager: he turned down {n['give_names']} for {n['get_names']}" + (f" ({n['note']})" if n["note"] else "")
    return None


def manager_profile(db_path, team: TeamInfo, stats: dict[int, dict], market: Optional[Market] = None) -> dict:
    negs = negotiations(db_path, team.team_id)
    st = stats.get(team.team_id, {"trades": 0, "adds": 0, "drops": 0, "last_trade": 0.0})
    counts = {k: sum(1 for n in negs if n["response"] == k) for k in ("accepted", "rejected", "countered", "pending")}
    t = tendency(negs)
    return {"team": team.name, "owner": team.owner_label, "record": team.record, "playoff_pct": team.playoff_pct, "trades_this_season": st["trades"], "adds": st["adds"], "drops": st["drops"],
            "logged": counts, "tendency_logit": round(t, 2),
            "tendency_text": ("no logged negotiations yet - using the league-wide prior" if not negs else
                              "has said yes more often than the model predicted" if t > 0.25 else "has said no more often than the model predicted" if t < -0.25 else "behaving about as the model predicts"),
            "notes": [{"when": time.strftime("%b %-d", time.localtime(n["ts"])), "offer": f"{n['give_names']} for {n['get_names']}", "response": n["response"], "note": n["note"]} for n in negs[:6]]}


# ---- the model ----------------------------------------------------------------------------------------------------
def assess(market: Market, season: Season, other: TeamInfo, give: list[PlayerInfo], get: list[PlayerInfo], their_delta_ppg: float, their_depth_unused: bool,
           stats: dict[int, dict], negs: list[dict], their_roster_after: Optional[list[PlayerInfo]] = None) -> Acceptance:
    """`give` = what I send (they receive), `get` = what I ask for (they give up). their_delta_ppg = change in THEIR average weekly lineup points."""
    sigs: list[Signal] = []
    recv, sent = market.package(give), market.package(get)
    drop_cost = 0.0
    if their_roster_after is not None and len(give) > len(get):
        drop = season.worst_droppable(their_roster_after, protect={p.player_id for p in give})
        if drop is not None:
            drop_cost = 0.25 * market.worth(market.value(drop))
    r = max(recv - drop_cost, 0.01) / (max(recv - drop_cost, 0.01) + sent)
    sigs.append(Signal("market fairness", FAIR_SCALE * (r - FAIR_CENTER),
                       f"by consensus value he gets {100 * r:.0f}% of the combined worth" + (f" (after clearing a roster spot)" if drop_cost else "")))
    need = max(-0.7, min(0.7, 0.12 * their_delta_ppg))
    sigs.append(Signal("need fit", need, f"their starting lineup changes by {their_delta_ppg:+.1f} pts/week on average" + (", and the player he gives up isn't a starter for him" if their_depth_unused else "")))
    if their_depth_unused:
        sigs.append(Signal("surplus", 0.3, "he's giving up depth he isn't using"))
    contender = other.playoff_pct >= 50
    out_of_race = other.playoff_pct < 25 and other.wins + other.losses >= 3
    hurt_in = [p for p in give if season.timeline(p).expected_games_out >= 3]
    if hurt_in:
        sigs.append(Signal("their situation", -0.35 if contender else 0.4 if out_of_race else 0.0,
                           f"{hurt_in[0].name} is hurt: " + ("a contender wants help now" if contender else "a team out of the race can afford to wait" if out_of_race else "neutral for a mid-table team")))
    brand = sum(market.row(p).brand for p in give) - sum(market.row(p).brand for p in get)
    sigs.append(Signal("name value", max(-0.6, min(0.6, 0.012 * brand)), "he's getting " + ("more name value than he's giving" if brand > 0 else "less name value than he's giving")))
    st = stats.get(other.team_id, {"trades": 0})
    sigs.append(Signal("trade history", 0.25 if st["trades"] >= 3 else 0.1 if st["trades"] >= 1 else -0.15,
                       f"{st['trades']} trade{'s' if st['trades'] != 1 else ''} made this season"))
    mine = [n for n in negs if n["team_id"] == other.team_id]
    t = tendency(mine)
    if mine:
        sigs.append(Signal("negotiation history", t, f"{len(mine)} logged negotiation{'s' if len(mine) != 1 else ''}: " + ("says yes more than expected" if t > 0.25 else "says no more than expected" if t < -0.25 else "as expected")))
    logit = BASE + sum(s.contribution for s in sigs)
    conf = confirmed_override(mine, {p.player_id for p in give}, {p.player_id for p in get})
    if conf:
        return Acceptance(conf[0], logit, sigs, conf[1], r)
    return Acceptance(label_for(logit), logit, sigs, None, r)
