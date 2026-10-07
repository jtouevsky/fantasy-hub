"""Stability-weighted player value: split fantasy points into volume points and touchdown points, regress each toward what the player's
OPPORTUNITY says it should be (touchdowns heavily, volume lightly), and describe the weekly distribution (floor / median / ceiling).

    stable_ppg = (g*vol_actual + kv*vol_expected)/(g+kv)  +  (g*td_actual + ktd*td_expected)/(g+ktd)        g = games in the last WINDOW

* vol points = everything except touchdown points (yards, receptions, turnovers), under THIS league's scoring.
* td points  = passing/rushing/receiving TDs x the league's TD values.
* expected volume / expected TDs come from nflverse ff_opportunity (expected stats from the quality of every target, carry and pass).
* kv and ktd are FIT, not guessed: `python -m edge.stable` tunes them on 2024 and validates on 2025 (docs/backtest.md).
"""
from __future__ import annotations

import json
import os
from typing import Optional

import numpy as np
import pandas as pd

from edge import scoring
from edge.history import Hist

WINDOW = 8
MIN_GAMES = 3
PARAMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stable_params.json")
DEFAULT = {"kv": 4.0, "ktd": 12.0, "window": WINDOW, "quant": {}}
POS = ["QB", "RB", "WR", "TE"]
BUCKETS = [(0.0, 0.25, "low"), (0.25, 0.40, "mid"), (0.40, 9.0, "high")]          # share of points that come from touchdowns


def td_weights(w: dict) -> dict:
    return {"pass": w.get("passing_tds", 4.0), "rush": w.get("rushing_tds", 6.0), "rec": w.get("receiving_tds", 6.0)}


def game_table(h: Hist, w: Optional[dict] = None) -> pd.DataFrame:
    """One row per player-game with points split into volume / touchdown parts, actual and expected, under the league scoring `w`."""
    w = w or scoring.weights()
    t = td_weights(w)
    x = h.xfp.copy()
    wk = h.weekly[["gsis", "t", "name", "pos", "team", "pts", "passing_tds", "rushing_tds", "receiving_tds", "carries", "targets", "target_share"]]
    d = wk.merge(x.drop(columns=["season", "week"]), on=["gsis", "t"], how="inner")
    for c in ("passing_tds", "rushing_tds", "receiving_tds", "carries", "targets"):
        d[c] = d[c].fillna(0)
    d["td_pts"] = d.passing_tds * t["pass"] + d.rushing_tds * t["rush"] + d.receiving_tds * t["rec"]
    d["vol_pts"] = d.pts - d.td_pts
    d["xtd_pts"] = d.pass_touchdown_exp.fillna(0) * t["pass"] + d.rush_touchdown_exp.fillna(0) * t["rush"] + d.rec_touchdown_exp.fillna(0) * t["rec"]
    d["xvol_pts"] = (d.receptions_exp.fillna(0) * w.get("receptions", 1.0) + d.rec_yards_gained_exp.fillna(0) * w.get("receiving_yards", 0.1)
                     + d.rush_yards_gained_exp.fillna(0) * w.get("rushing_yards", 0.1) + d.pass_yards_gained_exp.fillna(0) * w.get("passing_yards", 0.04)
                     + d.pass_interception_exp.fillna(0) * w.get("passing_interceptions", -2.0))
    d["season"] = d.t // 100
    d["week"] = d.t % 100
    return d.sort_values(["gsis", "t"]).reset_index(drop=True)


def _roll(d: pd.DataFrame, col: str, window: int, min_periods: int = MIN_GAMES) -> pd.Series:
    return d.groupby("gsis")[col].transform(lambda s: s.shift(1).rolling(window, min_periods=min_periods).mean())


def asof_frame(d: pd.DataFrame, window: int = WINDOW) -> pd.DataFrame:
    """Pre-game rolling means (the game itself excluded) for every player-game."""
    o = d[["gsis", "t", "season", "week", "pos", "pts"]].copy()
    for c in ("vol_pts", "td_pts", "xvol_pts", "xtd_pts", "pts", "carries", "targets"):
        o["m_" + c] = _roll(d, c, window)
    o["g"] = d.groupby("gsis")["pts"].transform(lambda s: s.shift(1).rolling(window, min_periods=MIN_GAMES).count())
    o["raw4"] = _roll(d, "pts", 4, 2)
    return o


def estimate(m_vol, m_td, x_vol, x_td, g, kv: float, ktd: float):
    g = np.asarray(g, dtype=float)
    return (g * m_vol + kv * x_vol) / (g + kv) + (g * m_td + ktd * x_td) / (g + ktd)


def fit(o: pd.DataFrame, train_seasons: list[int], kvs=(0, 1, 2, 4, 8, 16), ktds=(0, 2, 5, 10, 20, 40, 100)) -> dict:
    """Grid-search the two regression strengths on `train_seasons` (minimizes squared error of next-game points; players with a real role only)."""
    m = o[o.season.isin(train_seasons) & o.g.notna() & (o.m_pts >= 3.0)]
    best = None
    grid = {}
    for kv in kvs:
        for ktd in ktds:
            e = estimate(m.m_vol_pts, m.m_td_pts, m.m_xvol_pts.fillna(m.m_vol_pts), m.m_xtd_pts.fillna(m.m_td_pts), m.g, kv, ktd)
            mse = float(np.mean((m.pts - e) ** 2))
            grid[(kv, ktd)] = mse
            if best is None or mse < best[0]:
                best = (mse, kv, ktd)
    return {"kv": float(best[1]), "ktd": float(best[2]), "mse": best[0], "grid": grid, "raw_mse": float(np.mean((m.pts - m.m_pts) ** 2)), "n": int(len(m))}


def spearman_by_week(df: pd.DataFrame, a: str, b: str) -> float:
    out = []
    for _, g in df.groupby(["season", "week"]):
        if len(g) >= 20:
            out.append(g[a].rank().corr(g[b].rank()))
    return float(np.nanmean(out)) if out else float("nan")


def evaluate(o: pd.DataFrame, seasons: list[int], kv: float, ktd: float) -> dict:
    m = o[o.season.isin(seasons) & o.g.notna() & (o.m_pts >= 3.0)].copy()
    m["est"] = estimate(m.m_vol_pts, m.m_td_pts, m.m_xvol_pts.fillna(m.m_vol_pts), m.m_xtd_pts.fillna(m.m_td_pts), m.g, kv, ktd)
    mae = lambda c: float(np.mean(np.abs(m.pts - m[c])))
    return {"n": int(len(m)), "mae_raw8": mae("m_pts"), "mae_raw4": float(np.mean(np.abs(m.pts - m.raw4.fillna(m.m_pts)))), "mae_stable": mae("est"),
            "rho_raw8": spearman_by_week(m, "m_pts", "pts"), "rho_stable": spearman_by_week(m, "est", "pts"), "frame": m}


def ros_rank_corr(o: pd.DataFrame, season: int, kv: float, ktd: float, week: int = 5) -> dict:
    """At the decision week: does the estimate rank players by their ACTUAL points over the rest of the season (weeks week..17)?"""
    a = o[(o.season == season) & (o.week == week) & o.g.notna() & (o.m_pts >= 3.0)].copy()
    a["est"] = estimate(a.m_vol_pts, a.m_td_pts, a.m_xvol_pts.fillna(a.m_vol_pts), a.m_xtd_pts.fillna(a.m_td_pts), a.g, kv, ktd)
    ros = o[(o.season == season) & (o.week >= week) & (o.week <= 17)].groupby("gsis").pts.sum().rename("ros")
    a = a.join(ros, on="gsis").dropna(subset=["ros"])
    mae_raw = float(np.mean(np.abs(a.ros / (17 - week + 1) - a.m_pts)))
    mae_st = float(np.mean(np.abs(a.ros / (17 - week + 1) - a.est)))
    return {"n": int(len(a)), "rho_raw": float(a.m_pts.rank().corr(a.ros.rank())), "rho_stable": float(a.est.rank().corr(a.ros.rank())), "mae_ppg_raw": mae_raw, "mae_ppg_stable": mae_st}


DEP_SHARE, DEP_TOUCH, DEP_MIN_PPG = 0.40, 9.0, 8.0     # TD-dependent: scoring >= 8 ppg with >= 40% of it from TDs on fewer than ~9 touches+targets per game
SHRINK_N = 20.0


def is_td_dependent(share, touches, ppg, pos: str = "WR") -> bool:
    return pos in ("RB", "WR", "TE") and ppg >= DEP_MIN_PPG and share >= DEP_SHARE and touches < DEP_TOUCH


def fit_penalty(frame: pd.DataFrame) -> float:
    """Extra points a TD-dependent player loses beyond the regression (mean of actual - estimate over flagged player-games), shrunk toward 0 by sample size."""
    f = frame.copy()
    f["share"] = (f.m_td_pts / f.m_pts.clip(lower=1.0)).clip(0, 1)
    f["touch"] = f.m_targets.fillna(0) + f.m_carries.fillna(0)
    d = f[(f.share >= DEP_SHARE) & (f.touch < DEP_TOUCH) & f.pos.isin(["RB", "WR", "TE"]) & (f.m_pts >= DEP_MIN_PPG)]
    if len(d) < 5:
        return 0.0
    return float((d.pts - d.est).mean() * len(d) / (len(d) + SHRINK_N))


def td_share_bucket(share: float) -> str:
    return next(n for lo, hi, n in BUCKETS if lo <= share < hi)


def quantile_table(frame: pd.DataFrame) -> dict:
    """Floor/median/ceiling multipliers: quantiles of (actual points / pre-game estimate) by position and TD-dependence bucket."""
    f = frame[frame.est >= 4.0].copy()
    f["share"] = (f.m_td_pts / f.m_pts.clip(lower=1.0)).clip(0, 1)
    f["bucket"] = f.share.map(td_share_bucket)
    f["ratio"] = f.pts / f.est
    out: dict = {}
    for pos in POS:
        out[pos] = {}
        for _, _, b in BUCKETS:
            r = f[(f.pos == pos) & (f.bucket == b)].ratio
            if len(r) >= 40:
                out[pos][b] = [round(float(r.quantile(q)), 3) for q in (0.2, 0.5, 0.8)] + [int(len(r))]
    return out


def load_params() -> dict:
    try:
        with open(PARAMS, encoding="utf-8") as fh:
            return {**DEFAULT, **json.load(fh)}
    except FileNotFoundError:
        return dict(DEFAULT)


def save_params(p: dict) -> None:
    with open(PARAMS, "w", encoding="utf-8") as fh:
        json.dump(p, fh, indent=2, sort_keys=True)


def td_dependence_check(frame: pd.DataFrame) -> dict:
    """Same trailing points per game, different sources: do touchdown-fueled players score less NEXT game than volume-backed ones?"""
    f = frame[(frame.m_pts >= 8) & (frame.m_pts <= 16) & frame.pos.isin(["WR", "RB", "TE"])].copy()
    f["share"] = (f.m_td_pts / f.m_pts.clip(lower=1.0)).clip(0, 1)
    f["touch"] = f.m_targets.fillna(0) + f.m_carries.fillna(0)
    td = f[(f.share >= 0.40) & (f.touch < 9)]
    vol = f[(f.share <= 0.20) & (f.touch >= 9)]
    return {"n_td": int(len(td)), "n_vol": int(len(vol)), "trailing_td": float(td.m_pts.mean()), "trailing_vol": float(vol.m_pts.mean()),
            "next_td": float(td.pts.mean()), "next_vol": float(vol.pts.mean()), "est_td": float(td.est.mean()), "est_vol": float(vol.est.mean())}


# ---------------------------------------------------------------------------------------------------------------------
# live: attach to the slate
# ---------------------------------------------------------------------------------------------------------------------
DEFAULT_RATIOS = {"QB": [0.55, 0.95, 1.5], "RB": [0.42, 0.9, 1.5], "WR": [0.4, 0.9, 1.5], "TE": [0.35, 0.85, 1.55]}
HIGH_TOUCH = {"RB": 14.0, "WR": 8.0, "TE": 6.0}          # touches (carries + targets) per game that count as a real, volume-backed role


def _ratios(params: dict, pos: str, share: float) -> list[float]:
    q = params.get("quant", {}).get(pos, {})
    row = q.get(td_share_bucket(share)) or q.get("mid") or next(iter(q.values()), None)
    return list(row[:3]) if row else list(DEFAULT_RATIOS.get(pos, [0.4, 0.9, 1.5]))


def player_stable(rows: pd.DataFrame, pos: str, params: dict) -> Optional[dict]:
    """`rows`: this player's most recent games (oldest first) from game_table(). Returns the stability profile, or None without enough games."""
    r = rows.tail(params.get("window", WINDOW))
    g = len(r)
    if g < MIN_GAMES:
        return None
    m = r.mean(numeric_only=True)
    est = float(estimate(m.vol_pts, m.td_pts, m.xvol_pts if m.xvol_pts == m.xvol_pts else m.vol_pts, m.xtd_pts if m.xtd_pts == m.xtd_pts else m.td_pts, g, params["kv"], params["ktd"]))
    share = float(np.clip(m.td_pts / max(m.pts, 1.0), 0, 1))
    touches = float(m.targets + m.carries)
    dep = is_td_dependent(share, touches, float(m.pts), pos)
    if dep:
        est += params.get("dep_penalty", 0.0)
    vol_backed = pos in HIGH_TOUCH and touches >= HIGH_TOUCH[pos] and share <= 0.30
    return {"ppg": round(max(est, 0.0), 2), "g": int(g), "raw_ppg": round(float(m.pts), 2), "vol_pg": round(float(m.vol_pts), 2), "td_pg": round(float(m.td_pts), 2),
            "xvol_pg": round(float(m.xvol_pts), 2), "xtd_pg": round(float(m.xtd_pts), 2), "td_share": round(share, 3), "touches_pg": round(touches, 1),
            "targets_pg": round(float(m.targets), 1), "carries_pg": round(float(m.carries), 1), "target_share": round(float(m.target_share), 3) if m.target_share == m.target_share else None,
            "td_exp_pg": round(float(m.pass_touchdown_exp + m.rush_touchdown_exp + m.rec_touchdown_exp), 2), "td_act_pg": round(float(m.passing_tds + m.rushing_tds + m.receiving_tds), 2),
            "dependent": bool(dep), "volume_backed": bool(vol_backed), "r": _ratios(params, pos, share)}


def live_stable(h: Hist, players: list, gsis_of: dict[int, str], season: int, week: int, w: Optional[dict] = None, params: Optional[dict] = None) -> dict[int, dict]:
    params = params or load_params()
    tbl = getattr(h, "_stable_tbl", None)
    if tbl is None:
        tbl = h._stable_tbl = game_table(h, w)
    tw = season * 100 + week
    past = tbl[tbl.t < tw]
    by = {g: df for g, df in past.groupby("gsis")}
    sn = h.snaps[(h.snaps.t < tw) & (h.snaps.offense_pct > 0)].sort_values("t")
    snaps = {g: df.offense_pct.tail(4).mean() for g, df in sn.groupby("gsis")}
    rz = getattr(h, "rz", None)
    rzg = {}
    if rz is not None and len(rz):
        r = rz[rz.t < tw]
        rzg = {g: df for g, df in r.groupby("gsis")}
    out = {}
    for p in players:
        g = gsis_of.get(p.player_id)
        if g in by and p.position in POS:
            prof = player_stable(by[g], p.position, params)
            if prof:
                prof["snap_pct"] = round(float(snaps[g]), 3) if g in snaps else None
                if g in rzg:
                    last = by[g].tail(params.get("window", WINDOW))
                    rr = rzg[g][rzg[g].t.isin(last.t)]
                    n = max(len(last), 1)
                    prof["rz_touch_pg"] = round(float((rr.rz_carries.sum() + rr.rz_targets.sum()) / n), 2)
                    prof["gl_touch_pg"] = round(float((rr.gl_carries.sum() + rr.gl_targets.sum()) / n), 2)
                out[p.player_id] = prof
    return out


def dist_ratios(p) -> Optional[list]:
    return (p.stable or {}).get("r")


def tags_for(p, role_dsnap: Optional[float] = None) -> list[tuple[str, str]]:
    """TD-dependent / volume-backed tags with the numbers that justify them."""
    s = p.stable
    if not s:
        return []
    out = []
    if s["dependent"]:
        out.append(("td-dependent", f"{s['td_share'] * 100:.0f}% of his points come from touchdowns on only {s['touches_pg']:.1f} touches+targets per game "
                                    f"({s['td_act_pg']:.2f} TDs/game vs {s['td_exp_pg']:.2f} expected). The model counts him at {s['ppg']:.1f} ppg, not his raw {s['raw_ppg']:.1f}."))
    elif s["volume_backed"]:
        out.append(("volume-backed", f"{s['touches_pg']:.1f} touches+targets per game and only {s['td_share'] * 100:.0f}% of his points from TDs: his production is built on volume, so it is stable."))
    return out


def apply_to_players(players: list, mapping: dict[int, dict]) -> None:
    for p in players:
        s = mapping.get(p.player_id)
        p.stable = dict(s) if s else {}
        if s:
            have = {t[0] for t in p.tags}
            p.tags = list(p.tags) + [list(t) for t in tags_for(p) if t[0] not in have]


def main() -> None:
    h = Hist.load([2023, 2024, 2025], scoring.weights())
    d = game_table(h)
    o = asof_frame(d)
    f24 = fit(o, [2024])
    kv, ktd = f24["kv"], f24["ktd"]
    print(f"fit on 2024 (n={f24['n']}): kv={kv} ktd={ktd}  mse {f24['mse']:.3f} vs raw trailing mean {f24['raw_mse']:.3f}")
    print("grid mse (rows kv, cols ktd):")
    for k in sorted({a for a, _ in f24["grid"]}):
        print(f"  kv={k:>4}: " + " ".join(f"{f24['grid'][(k, t)]:7.2f}" for t in sorted({t for _, t in f24["grid"]})))
    for s in (2024, 2025):
        e = evaluate(o, [s], kv, ktd)
        print(f"{s}: n={e['n']} MAE raw8 {e['mae_raw8']:.3f} raw4 {e['mae_raw4']:.3f} stable {e['mae_stable']:.3f} | rank corr raw8 {e['rho_raw8']:.3f} stable {e['rho_stable']:.3f}")
        r = ros_rank_corr(o, s, kv, ktd)
        print(f"   rest of season from week 5: n={r['n']} rank corr raw {r['rho_raw']:.3f} stable {r['rho_stable']:.3f}; MAE of ppg raw {r['mae_ppg_raw']:.2f} stable {r['mae_ppg_stable']:.2f}")
        c = td_dependence_check(e["frame"])
        print(f"   same-ppg check: TD-fueled (n={c['n_td']}) trailing {c['trailing_td']:.2f} -> next {c['next_td']:.2f} (model {c['est_td']:.2f}); volume-backed (n={c['n_vol']}) trailing {c['trailing_vol']:.2f} -> next {c['next_vol']:.2f} (model {c['est_vol']:.2f})")
    e24 = evaluate(o, [2024], kv, ktd)
    q = quantile_table(e24["frame"])
    e25 = evaluate(o, [2025], kv, ktd)["frame"]
    e25["share"] = (e25.m_td_pts / e25.m_pts.clip(lower=1.0)).clip(0, 1)
    below = above = n = 0
    for r in e25[e25.est >= 4].itertuples():
        row = q.get(r.pos, {}).get(td_share_bucket(r.share))
        if row:
            n += 1
            below += r.pts < row[0] * r.est
            above += r.pts > row[2] * r.est
    print(f"floor/ceiling coverage on 2025 (fit on 2024): {100 * below / n:.0f}% below the 20th pct (target 20), {100 * above / n:.0f}% above the 80th (target 20), n={n}")
    pen = fit_penalty(e24["frame"])
    d25 = e25.copy()
    d25["touch"] = d25.m_targets.fillna(0) + d25.m_carries.fillna(0)
    flag = (d25.share >= DEP_SHARE) & (d25.touch < DEP_TOUCH) & d25.pos.isin(["RB", "WR", "TE"]) & (d25.m_pts >= DEP_MIN_PPG)
    adj = d25.est + pen * flag
    print(f"TD-dependent penalty fit on 2024: {pen:.2f} pts/game; 2025 flagged n={int(flag.sum())}: MAE {np.mean(np.abs(d25.pts - d25.est)[flag]):.2f} -> {np.mean(np.abs(d25.pts - adj)[flag]):.2f}; overall MAE {np.mean(np.abs(d25.pts - d25.est)):.3f} -> {np.mean(np.abs(d25.pts - adj)):.3f}")
    save_params({"kv": kv, "ktd": ktd, "window": WINDOW, "dep_penalty": round(pen, 3), "quant": q})
    print("saved", PARAMS)


if __name__ == "__main__":
    main()
