"""Add/drop moves: ONE engine used by the Waivers page, optimizer, Overview cards and the AI assistant.

Every move is scored by re-solving my week-by-week lineup with and without it (season.py), then passed through a deterministic validation layer
(position caps, streaming rules, recently-added protection, "never cut a starter for a backup", projection sanity). The assistant may only
recommend what `find_moves()` returns; "no move needed" is a valid, common answer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from models import LeagueSnapshot, PlayerInfo
from season import Season
from strategy import Strategy

DAY = 86400.0
STARTER_SHARE = 0.4            # a player who starts in at least this share of remaining weeks is "starter-caliber"
SPIKE_POINTS = 4.0             # a one-week projection this far above his own level (and > 50%) is treated as an outlier
DST_BLEND = 0.5                # D/ST this-week estimate = blend of ESPN's number and the matchup model


@dataclass
class Move:
    add: PlayerInfo
    drop: Optional[PlayerInfo]
    gain_week: float                       # this week, expected starting-lineup points
    gain_ros: float                        # rest of season (playoff weeks weighted), expected lineup points
    reason: str
    confidence: str = "medium"             # high / medium / low
    kind: str = "add_drop"                 # add_drop | add | stream
    flags: list[str] = field(default_factory=list)       # speculative, streamer, ...
    blocked: list[str] = field(default_factory=list)     # validation failures (the move must not be shown if any)
    starts: int = 0                        # weeks he would start for me
    weeks: int = 0

    @property
    def ok(self) -> bool:
        return not self.blocked

    @property
    def score(self) -> float:
        return self.gain_ros + self.gain_week

    def action(self) -> str:
        d = f" and drop {self.drop.name}" if self.drop else ""
        return f"In the ESPN app: add {self.add.name} ({self.add.position}, {self.add.pro_team}){d}. Waiver claims process on your league's waiver day."

    def to_dict(self) -> dict:
        return {"add": self.add.name, "add_id": self.add.player_id, "position": self.add.position, "drop": self.drop.name if self.drop else None,
                "drop_id": self.drop.player_id if self.drop else None, "gain_this_week": round(self.gain_week, 1), "gain_rest_of_season": round(self.gain_ros, 1),
                "confidence": self.confidence, "reason": self.reason, "flags": self.flags, "kind": self.kind}


@dataclass
class StreamPick:
    position: str
    current: Optional[PlayerInfo]
    best: Optional[PlayerInfo]
    current_pts: float
    best_pts: float
    swap: bool
    reason: str
    plan_ahead: str = ""

    @property
    def gain(self) -> float:
        return self.best_pts - self.current_pts

    def to_dict(self) -> dict:
        return {"position": self.position, "current": self.current.name if self.current else None, "best": self.best.name if self.best else None,
                "swap": self.swap, "this_week_gain": round(self.gain, 1), "reason": self.reason, "plan_ahead": self.plan_ahead}


@dataclass
class MoveSet:
    moves: list[Move]
    streams: list[StreamPick]
    no_move_reason: str = ""

    @property
    def empty(self) -> bool:
        return not self.moves and not any(s.swap for s in self.streams)

    def to_dict(self) -> dict:
        return {"moves": [m.to_dict() for m in self.moves], "streaming": [s.to_dict() for s in self.streams], "no_move_needed": self.empty,
                "no_move_reason": self.no_move_reason if self.empty else ""}


class MoveEngine:
    def __init__(self, snap: LeagueSnapshot, season: Season, strategy: Strategy, fas: list[PlayerInfo], activity: list[dict] = (),
                 dst: Optional[dict] = None, dst_next: Optional[dict] = None, now: Optional[float] = None):
        self.snap, self.season, self.strategy, self.fas = snap, season, strategy, list(fas)
        self.now = now if now is not None else time.time()
        self.dst, self.dst_next = dst or {}, dst_next or {}
        self.me = snap.my_team
        self.caps = strategy.caps(snap.starter_slots)
        self.added_ts: dict[int, float] = {}
        self.dropped_ts: dict[int, float] = {}
        for a in activity:
            if a.get("team_id") != self.me.team_id or a.get("player_id") is None:
                continue
            act, ts, pid = a.get("action", ""), a.get("ts", 0.0), int(a["player_id"])
            if "ADDED" in act:
                self.added_ts[pid] = max(self.added_ts.get(pid, 0.0), ts)
            elif act == "DROPPED":
                self.dropped_ts[pid] = max(self.dropped_ts.get(pid, 0.0), ts)
        for p in self.me.roster:                               # PlayerInfo.added_ts wins if the data layer set it
            if p.added_ts:
                self.added_ts[p.player_id] = p.added_ts
        self._before = season.season_lineup(self.me.roster, use_pool=False)

    # ---- helpers -------------------------------------------------------------------------
    def days_since(self, ts: float) -> float:
        return (self.now - ts) / DAY

    def recently_added(self, p: PlayerInfo) -> bool:
        ts = self.added_ts.get(p.player_id)
        return ts is not None and self.days_since(ts) < self.strategy.recent_days

    def recently_dropped(self, p: PlayerInfo) -> Optional[float]:
        ts = self.dropped_ts.get(p.player_id)
        return self.days_since(ts) if ts is not None and self.days_since(ts) < self.strategy.recent_days else None

    def dst_pts(self, p: PlayerInfo, nxt: bool = False) -> tuple[float, str]:
        """D/ST this-week (or next-week) points: ESPN's adjusted number blended with the matchup model (a labelled estimate)."""
        env = (self.dst_next if nxt else self.dst).get(p.pro_team)
        base = p.week_proj if not nxt else self.season.model.ppg(p)
        if not env:
            return base, ""
        est = env["est"]
        pts = DST_BLEND * base + (1 - DST_BLEND) * est if not nxt else est
        return pts, "; ".join(env["reasons"][:2])

    def week_pts(self, p: PlayerInfo) -> float:
        if p.position == "D/ST":
            return self.dst_pts(p)[0] if not p.on_bye else 0.0
        return self.season.exp(p, self.season.week)

    def count(self, roster: list[PlayerInfo], pos: str) -> int:
        return sum(1 for p in roster if p.position == pos and p.lineup_slot != "IR")

    def spike(self, p: PlayerInfo) -> bool:
        """One-week outlier: ESPN's/edge's number is far above what he has actually been doing."""
        if p.position in ("D/ST", "K") or p.games_played < 3:
            return False
        ppg = self.season.model.ppg(p)
        return p.week_proj - ppg > max(SPIKE_POINTS, 0.5 * ppg)

    # ---- validation (deterministic; the assistant cannot bypass it) --------------------------
    def validate(self, add: PlayerInfo, drop: Optional[PlayerInfo], gain_week: float = 0.0, gain_ros: float = 0.0, starts_add: int = 0) -> list[str]:
        s, why = self.strategy, []
        rostered = {p.player_id for t in self.snap.teams for p in t.roster}
        if add.player_id in rostered:
            why.append(f"{add.name} is already on a roster, not a free agent.")
        if drop is not None and drop.player_id not in {p.player_id for p in self.me.roster}:
            why.append(f"{drop.name} is not on your roster.")
        if drop is not None and drop.lineup_slot == "IR":
            why.append(f"{drop.name} sits in your IR slot (it costs no bench spot), so cutting him frees nothing.")
        cap = self.caps.get(add.position)
        if cap is not None:
            if cap == 0:
                why.append(f"Your league has no {add.position} starting slot; never add one.")
            else:
                n = self.count(self.me.roster, add.position) - (1 if drop and drop.position == add.position else 0) + 1
                if n > cap:
                    why.append(f"Roster cap: you can hold at most {cap} {add.position}; adding another requires dropping one of your {add.position}s.")
        if drop is None and self.season.roster_count(self.me.roster) >= self.season.capacity:
            why.append("Your roster is full; a drop is required.")
        if drop is not None:
            starts = self._before["starts"].get(drop.player_id, 0)
            if starts >= STARTER_SHARE * len(self.season.weeks) and starts_add == 0:
                why.append(f"{drop.name} starts for you most weeks; never cut a starter for a backup.")
            if self.recently_added(drop):
                d = self.days_since(self.added_ts[drop.player_id])
                if not (gain_week >= s.recent_override_gain and drop.injury_status not in ("ACTIVE", "")):
                    why.append(f"You added {drop.name} {d:.0f} day(s) ago; not churning him without new injury news and a big gain.")
        d_add = self.recently_dropped(add)
        if d_add is not None:
            why.append(f"You dropped {add.name} {d_add:.0f} day(s) ago; no add/drop ping-pong.")
        if add.position in s.streaming and add.position in ("D/ST", "K"):
            sp = self.stream_pick(add.position)
            if not (sp.swap and sp.best and sp.best.player_id == add.player_id):
                why.append(sp.reason if not sp.swap else f"The best {add.position} this week is {sp.best.name if sp.best else 'someone else'}, not {add.name}.")
        return why

    # ---- scoring -------------------------------------------------------------------------
    def evaluate_move(self, add: PlayerInfo, drop: Optional[PlayerInfo]) -> Move:
        s = self.season
        new = [p for p in self.me.roster if not (drop and p.player_id == drop.player_id)] + [add]
        after = s.season_lineup(new, use_pool=False)
        before = self._before
        gain_ros = after["total"] - before["total"]
        gain_week = after["weeks"][0][1] - before["weeks"][0][1]
        starts = after["starts"].get(add.player_id, 0)
        flags: list[str] = []
        if add.position == "D/ST" or add.position == "K":
            gain_week = self.week_pts(add) - (self.week_pts(drop) if drop and drop.position == add.position else 0.0)
            flags.append("streamer")
        mv = Move(add, drop, gain_week, gain_ros, "", flags=flags, starts=starts, weeks=len(s.weeks))
        mv.blocked = self.validate(add, drop, gain_week, gain_ros, starts)
        need_ros, need_week = self.strategy.min_gain_ros, self.strategy.min_gain_week
        if self.spike(add):
            flags.append("speculative")
            need_ros += self.strategy.speculative_extra_gain
            need_week += self.strategy.speculative_extra_gain
        if not mv.blocked and not ("streamer" in flags) and gain_week < need_week and gain_ros < need_ros:
            mv.blocked.append(f"Gain too small (+{gain_week:.1f} this week, +{gain_ros:.1f} rest of season)" + (" for a one-week projection spike." if "speculative" in flags else "."))
        mv.confidence = self._confidence(mv)
        mv.reason = self.explain(mv)
        return mv

    def _confidence(self, m: Move) -> str:
        if "speculative" in m.flags or m.add.games_played < 2:
            return "low"
        if m.gain_ros >= 12 and m.starts >= 0.5 * max(m.weeks, 1):
            return "high"
        return "medium"

    def explain(self, m: Move) -> str:
        a, d, beginner = m.add, m.drop, self.strategy.explanation == "Beginner"
        bits = []
        if m.starts and m.weeks:
            bits.append(f"{a.name} would start for you in {m.starts} of the next {m.weeks} weeks")
        else:
            bits.append(f"{a.name} would be a bench upgrade (no lineup change)")
        bits[0] += f": +{m.gain_week:.1f} this week, +{m.gain_ros:.1f} points rest of season"
        tail = []
        if d:
            why = "redundant at the position" if self.count(self.me.roster, d.position) > max(self.caps.get(d.position, 99), 0) or (d.position == "QB" and self.count(self.me.roster, "QB") > 1) \
                else "your least useful non-IR player"
            tail.append(f"Drop {d.name} ({why})")
        if "speculative" in m.flags:
            tail.append("speculative: his projection this week is far above his recent level, so this leans on one number")
        if a.edge:
            top = max(a.edge, key=lambda x: abs(x["delta"]))
            tail.append(top["reason"])
        elif a.tags:
            tail.append(f"tagged {a.tags[0][0]}")
        out = bits[0] + ("; " + "; ".join(tail[:2]) if tail else "") + "."
        if beginner and a.position == "D/ST":
            out += " (D/ST = a team's defense, scored on sacks, turnovers and points allowed.)"
        return out

    # ---- streaming -----------------------------------------------------------------------
    def stream_pick(self, pos: str) -> StreamPick:
        s = self.strategy
        mine = [p for p in self.me.roster if p.position == pos and p.lineup_slot != "IR"]
        cur = max(mine, key=self.week_pts) if mine else None
        cands = [p for p in self.fas if p.position == pos and not p.is_out]
        cands = [p for p in cands if self.recently_dropped(p) is None]
        best = max(cands, key=self.week_pts) if cands else None
        cur_pts = self.week_pts(cur) if cur else 0.0
        best_pts = self.week_pts(best) if best else 0.0
        name = {"D/ST": "D/ST", "K": "kicker"}.get(pos, pos)
        why_best = self.dst_pts(best)[1] if best and pos == "D/ST" else ""
        forced = cur is None or cur.on_bye or (cur.injury_status in ("OUT", "INJURY_RESERVE"))
        if best is None:
            return StreamPick(pos, cur, None, cur_pts, 0.0, False, f"No {name} free agents available; keep your current one.")
        gain = best_pts - cur_pts
        swap = bool(best.player_id != (cur.player_id if cur else None) and (forced or gain >= s.stream_swap_gain))
        if swap:
            if forced and cur is not None:
                reason = f"{cur.name} {'is on a bye' if cur.on_bye else 'is out'}; {best.name} projects {best_pts:.1f}."
            elif cur is None:
                reason = f"You have no {name}; {best.name} projects {best_pts:.1f}."
            else:
                reason = f"{best.name} projects {best_pts:.1f} vs {cur_pts:.1f} for {cur.name} (+{gain:.1f})" + (f": {why_best}" if why_best else "") + "."
        else:
            reason = f"Keep your current {name}" + (f" ({cur.name}, {cur_pts:.1f})" if cur else "") + f": the best alternative adds only {max(gain, 0):.1f} (< {s.stream_swap_gain:g} needed)."
        plan = ""
        if pos == "D/ST" and self.dst_next:
            nxt = [(self.dst_pts(p, True)[0], p) for p in self.fas if p.position == pos and p.pro_team in self.dst_next]
            if nxt:
                pts, who = max(nxt, key=lambda x: x[0])
                if who.player_id != (best.player_id if best else None) or True:
                    plan = f"Next week's best streamer so far: {who.name} (matchup estimate {pts:.1f})."
        if cur and pos == "D/ST" and cur.pro_team in self.dst:
            pass
        return StreamPick(pos, cur, best, cur_pts, best_pts, swap, reason, plan)

    # ---- drops ---------------------------------------------------------------------------
    def drop_candidates(self, add: PlayerInfo, limit: int = 4) -> list[Optional[PlayerInfo]]:
        """Redundancy first (a 3rd QB, a 2nd D/ST), then the least useful bench piece. Never IR, never a starter-caliber player."""
        s = self.season
        roster = [p for p in self.me.roster if p.lineup_slot != "IR"]
        starts = self._before["starts"]
        ok = [p for p in roster if starts.get(p.player_id, 0) < STARTER_SHARE * len(s.weeks) and p.player_id != add.player_id]
        out: list[Optional[PlayerInfo]] = []
        if s.roster_count(self.me.roster) < s.capacity:
            out.append(None)
        cap = self.caps.get(add.position)
        if cap is not None and self.count(self.me.roster, add.position) >= cap:
            same = sorted((p for p in ok if p.position == add.position), key=s.rank_key)
            return same[:limit]                                                        # a capped position can only swap within itself
        red = [p for p in ok if self.caps.get(p.position) is not None and self.count(self.me.roster, p.position) > self.caps[p.position] - 0]
        red += [p for p in ok if p.position in ("K", "D/ST") and self.caps.get(p.position, 0) == 0]
        rest = sorted((p for p in ok if p not in red and p.position not in ("K", "D/ST")), key=s.rank_key)
        for p in sorted(red, key=s.rank_key) + rest:
            if p not in out:
                out.append(p)
        return out[:limit]

    # ---- find ----------------------------------------------------------------------------
    def find_moves(self, max_moves: int = 3, pool: int = 24) -> MoveSet:
        s = self.season
        streams = [self.stream_pick(pos) for pos in sorted(self.strategy.streaming) if self.snap.starter_slots.get(pos)]
        cands = [p for p in self.fas if p.position in ("QB", "RB", "WR", "TE") and not p.is_out and not p.on_bye]
        short = sorted(cands, key=lambda p: -(s.raw_ros(p) + s.upside(p)))[:pool // 2] + sorted(cands, key=lambda p: -p.week_proj)[:pool // 2]
        seen, results = set(), []
        for fa in short:
            if fa.player_id in seen:
                continue
            seen.add(fa.player_id)
            best = None
            for d in self.drop_candidates(fa):
                mv = self.evaluate_move(fa, d)
                if mv.ok and (best is None or mv.score > best.score):
                    best = mv
            if best:
                results.append(best)
        # non-streaming K/D/ST moves are never proposed here: the streaming rules own those positions
        results.sort(key=lambda m: -m.score)
        picked, per_pos = [], {}
        for m in results:
            if per_pos.get(m.add.position, 0) < 1:
                per_pos[m.add.position] = 1
                picked.append(m)
        moves = picked[:max_moves]
        reason = ""
        if not moves and not any(x.swap for x in streams):
            reason = "Your lineup is set: no free agent clears the gain thresholds under your roster rules, and your streaming picks are already the best available."
        return MoveSet(moves, streams, reason)


def evaluate_move(eng: MoveEngine, add_id: int, drop_id: Optional[int]) -> Optional[Move]:
    pool = {p.player_id: p for p in eng.fas}
    mine = {p.player_id: p for p in eng.me.roster}
    add = pool.get(add_id) or next((p for t in eng.snap.teams for p in t.roster if p.player_id == add_id), None)
    if add is None:
        return None
    return eng.evaluate_move(add, mine.get(drop_id) if drop_id is not None else None)
