"""Module 1: vacated opportunity / injury cascade.

When a starter is Out / Doubtful / IR (or Questionable, weighted by how often that status really means 'out'), his share of
team carries and targets has to go somewhere. For each teammate T:

    expected_share_T = lam * share_T_without_X  +  (1 - lam) * (share_T_with_X + X_share * flow * T_depth_weight)
    lam              = n_without / (n_without + K)                (K = 3: a 3-game with/without sample counts 50%)
    delta_share_T    = expected_share_T - share_T_baseline        (baseline = what his last 4 games imply; avoids double counting)
    delta_points_T   = delta_carries * pts_per_carry_T + delta_targets * pts_per_target_T     (efficiency regressed to position average)

* with/without: nflverse games where X missed (injury report Out/Doubtful and no stats row) vs games X played, same team.
* depth fallback (small samples): X's share is spread over teammates in proportion to each one's current share, scaled by
  the league-wide flow rates between position groups - those flow rates are ESTIMATED from 2022-2023 events, not assumed.
* QBs are not cascaded (a QB change moves the whole offense; it isn't a simple share transfer).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from edge.history import Hist
from edge.modules.base import Module, empty_pred

K_LAMBDA = 3.0       # with/without shrinkage
K_CARRY = 40.0       # pseudo-carries at the position-average rate (efficiency regression)
K_TGT = 25.0         # pseudo-targets at the position-average rate
MIN_FLOW_EVIDENCE = 3.0   # summed X-share across events needed before a flow rate is trusted
MIN_X_SHARE = 0.08   # only cascade for absent players who actually had a role
SHARE_POS = ["RB", "WR", "TE"]
OUT_STATUS = {"Out", "Doubtful"}
DEFAULT_P_ABSENT = {"Out": 0.97, "Doubtful": 0.9, "Questionable": 0.3}
PRACTICE_KEY = {"Did Not Participate In Practice": "dnp", "Limited Participation in Practice": "limited", "Full Participation in Practice": "full"}


def practice_code(raw) -> str:
    return PRACTICE_KEY.get(raw, "") if isinstance(raw, str) else ""


def p_for(p_abs: dict, status: str, practice: str = "") -> float:
    """Probability a player with this report status (and, for Questionable, practice trend) does not play."""
    if status == "Questionable" and practice:
        v = p_abs.get(f"Questionable|{practice}")
        if v is not None:
            return v
    return p_abs.get(status, 0.0)


@dataclass
class Prep:
    W: pd.DataFrame                       # player-games with cs/ts shares, sorted by t
    by_team: dict[str, pd.DataFrame]
    played: set
    absent: set
    team_vol: pd.DataFrame                # (team, t) -> team carries / targets
    pos_of: dict[str, str]
    name_of: dict[str, str]
    inj_by_game: dict                     # (team, t) -> list[(gsis, status)]


def prep_for(h: Hist) -> Prep:
    cached = getattr(h, "_cascade_prep", None)
    if cached is not None:
        return cached
    W = h.weekly.copy()
    vol = W.groupby(["team", "t"], as_index=False).agg(vc=("carries", "sum"), vt=("targets", "sum"))
    W = W.merge(vol, on=["team", "t"], how="left")
    W["cs"] = (W.carries / W.vc.replace(0, np.nan)).fillna(0.0)
    W["ts"] = (W.targets / W.vt.replace(0, np.nan)).fillna(0.0)
    W = W.sort_values(["team", "t"]).reset_index(drop=True)
    played = set(zip(W.gsis, W.t))
    inj = h.inj[h.inj.report_status.isin(["Out", "Doubtful", "Questionable"])]
    inj_by_game: dict = {}
    absent = set()
    for r in inj.itertuples():
        inj_by_game.setdefault((r.team, r.t), []).append((r.gsis, r.report_status, practice_code(r.practice_status)))
        if r.report_status in OUT_STATUS and (r.gsis, r.t) not in played:
            absent.add((r.gsis, r.t))
    prep = Prep(W, {tm: g for tm, g in W.groupby("team")}, played, absent, vol.set_index(["team", "t"]),
                dict(zip(W.gsis, W.pos)), dict(zip(W.gsis, W.name)), inj_by_game)
    h._cascade_prep = prep
    return prep


def _recent(g: pd.DataFrame, gsis: str, tw: int, n: int) -> pd.DataFrame:
    r = g[(g.gsis == gsis) & (g.t < tw)]
    return r.tail(n)


def pos_rates(prep: Prep, pos: str, tw: int, lookback_games: int = 9000) -> tuple[float, float]:
    """League-wide points per carry / per target for a position, from games before tw."""
    w = prep.W[(prep.W.pos == pos) & (prep.W.t < tw)]
    ppc = w.rush_pts.sum() / max(w.carries.sum(), 1)
    ppt = w.rec_pts.sum() / max(w.targets.sum(), 1)
    return float(ppc), float(ppt)


def compute_team(prep: Prep, flows: dict, team: str, tw: int, absent: dict[str, float], active: Optional[set] = None) -> dict[str, dict]:
    """Cascade deltas for every teammate of `team` for the game at time `tw`.

    absent: {gsis: probability he does not play}. active: gsis allowed to receive volume (default: everyone who played recently).
    Returns {gsis: {delta, d_carries, d_targets, n_wo, causes: [(x_name, p, d_pts)], ...}}.
    """
    g = prep.by_team.get(team)
    if g is None or not absent:
        return {}
    recent = g[g.t < tw]
    if recent.empty:
        return {}
    last_ts = sorted(recent.t.unique())
    vol = recent[recent.t.isin(last_ts[-4:])].groupby("t").agg(vc=("carries", "sum"), vt=("targets", "sum"))
    V_c, V_t = float(vol.vc.mean()), float(vol.vt.mean())
    cand = recent[recent.t.isin(last_ts[-4:]) & recent.pos.isin(SHARE_POS)].gsis.unique()
    xs = {}
    for x, p in absent.items():
        if p <= 0 or prep.pos_of.get(x) not in SHARE_POS:
            continue
        xr = _recent(g, x, tw, 4)
        if xr.empty:
            continue
        cs, ts = float(xr.cs.mean()), float(xr.ts.mean())
        if cs < MIN_X_SHARE and ts < MIN_X_SHARE:
            continue
        xs[x] = (p, cs, ts)
    if not xs:
        return {}
    eligible = [t for t in cand if t not in absent or absent[t] < 0.9]
    if active is not None:
        eligible = [t for t in eligible if t in active]
    # baseline shares + depth weights
    base = {}
    for t in eligible:
        tr = _recent(g, t, tw, 4)
        base[t] = (float(tr.cs.mean()), float(tr.ts.mean()), prep.pos_of.get(t), len(tr))
    out: dict[str, dict] = {}
    rate_cache = {pos: pos_rates(prep, pos, tw) for pos in SHARE_POS}
    for t in eligible:
        tp = base[t][2]
        if tp not in SHARE_POS:
            continue
        t16 = g[(g.gsis == t) & (g.t < tw)].tail(16)
        d_c = d_t = 0.0
        causes, n_wo_max = [], 0
        for x, (p, xcs, xts) in xs.items():
            if x == t:
                continue
            xp = prep.pos_of.get(x)
            wo = t16[[(x, tt) in prep.absent for tt in t16.t]]
            wi = t16[[(x, tt) in prep.played for tt in t16.t]].tail(8)
            n_wo = len(wo)
            bcs, bts = base[t][0], base[t][1]
            w_cs = float(wi.cs.mean()) if len(wi) else bcs
            w_ts = float(wi.ts.mean()) if len(wi) else bts
            # depth fallback: X's share flows to teammates in proportion to their current share, by position group
            fc, ft = flows.get(xp, {}).get("carries", {}).get(tp, 0.0), flows.get(xp, {}).get("targets", {}).get(tp, 0.0)
            grp_c = sum(v[0] for k, v in base.items() if v[2] == tp and k != x) or 1e-9
            grp_t = sum(v[1] for k, v in base.items() if v[2] == tp and k != x) or 1e-9
            dep_c = w_cs + xcs * fc * (bcs / grp_c)
            dep_t = w_ts + xts * ft * (bts / grp_t)
            lam = n_wo / (n_wo + K_LAMBDA)
            exp_c = lam * (float(wo.cs.mean()) if n_wo else dep_c) + (1 - lam) * dep_c
            exp_t = lam * (float(wo.ts.mean()) if n_wo else dep_t) + (1 - lam) * dep_t
            dc, dt = p * (exp_c - bcs) * V_c, p * (exp_t - bts) * V_t
            d_c, d_t = d_c + dc, d_t + dt
            n_wo_max = max(n_wo_max, n_wo)
            causes.append((x, p, dc, dt, n_wo))
        if not causes:
            continue
        # points per touch for T, regressed to the position average
        ppc_pos, ppt_pos = rate_cache[tp]
        tall = g[(g.gsis == t) & (g.t < tw)].tail(16)
        ppc = (tall.rush_pts.sum() + K_CARRY * ppc_pos) / (tall.carries.sum() + K_CARRY)
        ppt = (tall.rec_pts.sum() + K_TGT * ppt_pos) / (tall.targets.sum() + K_TGT)
        pts = d_c * ppc + d_t * ppt
        out[t] = {"delta": float(pts), "d_carries": float(d_c), "d_targets": float(d_t), "n_wo": n_wo_max, "causes": causes, "ppc": float(ppc), "ppt": float(ppt)}
    return out


def explain(prep: Prep, info: dict, status_word: dict[str, str]) -> tuple[str, str]:
    """(reason, confidence) in plain English."""
    top = max(info["causes"], key=lambda c: abs(c[2] * info["ppc"] + c[3] * info["ppt"]))
    who = prep.name_of.get(top[0], "A teammate")
    st = status_word.get(top[0], "OUT")
    extra = f" (+{len(info['causes']) - 1} more out)" if len(info["causes"]) > 1 else ""
    conf = "high" if info["n_wo"] >= 3 else "med" if info["n_wo"] >= 1 else "low"
    basis = f"{info['n_wo']}-game with/without sample" if info["n_wo"] else "depth-chart/usage estimate, no with/without sample"
    parts = []
    if abs(info["d_carries"]) >= 0.4:
        parts.append(f"{info['d_carries']:+.1f} carries")
    if abs(info["d_targets"]) >= 0.4:
        parts.append(f"{info['d_targets']:+.1f} targets")
    return (f"{who} {st}{extra} → {', '.join(parts) or 'small share change'} → {info['delta']:+.1f} pts ({conf} confidence, {basis})", conf)


def estimate_flows(h: Hist, seasons: list[int]) -> dict:
    """Where does an absent starter's volume go? Pooled ratio of (teammates' share gain) to (X's share), by position pair."""
    prep = prep_for(h)
    acc: dict = {}
    for team, g in prep.by_team.items():
        g = g[g.season.isin(seasons)]
        for tw in sorted(g.t.unique()):
            ev = [(x, 1.0) for (x, t) in [(a, b) for (a, b) in prep.absent if b == tw] if prep.pos_of.get(x) in SHARE_POS
                  and any(r[0] == x for r in prep.inj_by_game.get((team, tw), []))]
            if not ev:
                continue
            full = prep.by_team[team]
            recent = full[full.t < tw]
            this = full[full.t == tw]
            for x, _ in ev:
                xr = _recent(full, x, tw, 4)
                if len(xr) < 2:
                    continue
                xcs, xts = float(xr.cs.mean()), float(xr.ts.mean())
                if xcs < MIN_X_SHARE and xts < MIN_X_SHARE:
                    continue
                xp = prep.pos_of[x]
                for t in this.gsis:
                    if t == x or prep.pos_of.get(t) not in SHARE_POS:
                        continue
                    tr = _recent(full, t, tw, 4)
                    if len(tr) < 2:
                        continue
                    row = this[this.gsis == t].iloc[0]
                    a = acc.setdefault(xp, {"carries": {}, "targets": {}, "x_c": 0.0, "x_t": 0.0})
                    tp = prep.pos_of[t]
                    a["carries"][tp] = a["carries"].get(tp, 0.0) + float(row.cs - tr.cs.mean())
                    a["targets"][tp] = a["targets"].get(tp, 0.0) + float(row.ts - tr.ts.mean())
                a = acc.setdefault(xp, {"carries": {}, "targets": {}, "x_c": 0.0, "x_t": 0.0})
                a["x_c"] += xcs
                a["x_t"] += xts
    flows = {}
    for xp, a in acc.items():
        # A flow is only trusted where the absent player had enough volume to measure it (e.g. TEs/WRs barely carry the ball,
        # so a 'carries' ratio there is noise) and is clamped to [0, 1]: you can't redistribute more than he had, or negative volume.
        c_ok, t_ok = a["x_c"] >= MIN_FLOW_EVIDENCE, a["x_t"] >= MIN_FLOW_EVIDENCE
        flows[xp] = {"carries": {tp: round(min(max(v / a["x_c"], 0.0), 1.0), 4) if c_ok else 0.0 for tp, v in a["carries"].items()},
                     "targets": {tp: round(min(max(v / a["x_t"], 0.0), 1.0), 4) if t_ok else 0.0 for tp, v in a["targets"].items()}}
    return flows


def estimate_p_absent(h: Hist, seasons: list[int]) -> dict:
    """How often does each injury-report status actually mean 'did not play'? Questionable is split by practice trend
    (did not practice / limited / full). Skill positions only; a bucket needs >= 20 cases."""
    prep = prep_for(h)
    n, k = {}, {}
    for r in h.inj[h.inj.season.isin(seasons)].itertuples():
        if prep.pos_of.get(r.gsis) not in SHARE_POS or r.report_status not in ("Out", "Doubtful", "Questionable"):
            continue
        keys = [r.report_status]
        pc = practice_code(r.practice_status)
        if r.report_status == "Questionable" and pc:
            keys.append(f"Questionable|{pc}")
        for key in keys:
            n[key] = n.get(key, 0) + 1
            if (r.gsis, r.t) not in prep.played:
                k[key] = k.get(key, 0) + 1
    return {key: round(k.get(key, 0) / n[key], 3) for key in n if n[key] >= 20} or dict(DEFAULT_P_ABSENT)


class Cascade(Module):
    name = "Injury cascade (vacated opportunity)"
    kind = "cascade"

    def fit(self, h, rows):
        seasons = sorted(h.weekly.season.unique())
        first_eval = int(rows.season.min()) if len(rows) else max(seasons)
        train = [s for s in seasons if s < first_eval]
        self.coefs = {"flows": estimate_flows(h, train), "p_absent": estimate_p_absent(h, train), "scale": {}}
        # Calibration: the raw share-transfer estimate over-shoots (opportunity gains regress toward the mean), so fit one
        # least-squares scale per position on the training rows. Ridge keeps it conservative where evidence is thin.
        raw = self._raw(h, rows)
        res = rows.pts - rows.base
        for pos in SHARE_POS:
            m = (rows.pos == pos) & (raw.delta.abs() >= 0.5)
            d, y = raw.delta[m].to_numpy(), res[m].to_numpy()
            self.coefs["scale"][pos] = round(float(np.clip((d @ y) / (d @ d + 25.0), 0.0, 1.0)), 3) if len(d) >= 30 else 0.5
        return self

    def _raw(self, h, rows):
        out = empty_pred(rows.index)
        prep = prep_for(h)
        flows, p_abs = self.coefs.get("flows", {}), self.coefs.get("p_absent", DEFAULT_P_ABSENT)
        for (team, t), idx in rows.groupby(["team", "t"]).groups.items():
            absent = {gsis: p_for(p_abs, st, pr) for gsis, st, pr in prep.inj_by_game.get((team, t), [])}
            res = compute_team(prep, flows, team, t, absent)
            status = {gsis: ("OUT" if st in OUT_STATUS else "QUESTIONABLE") for gsis, st, pr in prep.inj_by_game.get((team, t), [])}
            for i in idx:
                info = res.get(rows.at[i, "gsis"])
                if info is None:
                    continue
                reason, conf = explain(prep, info, status)
                out.at[i, "delta"], out.at[i, "reason"], out.at[i, "confidence"] = info["delta"], reason, conf
        return out

    def predict(self, h, rows):
        out = self._raw(h, rows)
        scale = rows.pos.map(self.coefs.get("scale", {})).fillna(0.5)
        out["delta"] = out["delta"] * scale
        return out
