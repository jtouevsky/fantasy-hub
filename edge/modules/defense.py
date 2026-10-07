"""Module 2: opposing defense injuries and pass rush vs. protection.

Features for each offensive player-game (all from the pre-game injury report, snap history and play-by-play):
  n_db    starting CBs/safeties on the opposing defense who are out        (more passing success for QB/WR/TE)
  n_rush  starting pass rushers (DE/DT/DL) on the opposing defense who are out
  n_ol    the player's own offensive linemen who are out  (OL are not in nflverse snap counts, so we count listed OL, not 'starters')
  press   matchup of the defense's recent pressure rate (sacks + QB hits per dropback) and the offense's pressure allowed
A defender is a 'starter' if he played >= 60% (DBs) / 50% (rushers) of defensive snaps over his team's last 4 games.
Effects are estimated from nflverse history (least squares on residuals), not assumed, and kept small by a ridge penalty.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from edge.modules.base import Module, empty_pred, ols_through_origin
from edge.modules.cascade import DEFAULT_P_ABSENT, estimate_p_absent, p_for, practice_code

DB_POS = {"CB", "S", "FS", "SS", "DB"}
RUSH_POS = {"DE", "DT", "DL", "NT"}
OL_POS = {"T", "G", "C", "OT", "OG", "LT", "RT", "LG", "RG"}
FEATURES = ["n_db", "n_rush", "n_ol", "press"]
POS = ["QB", "RB", "WR", "TE"]


def _prep(h):
    c = getattr(h, "_defense_prep", None)
    if c is not None:
        return c
    sn = h.snaps[(h.snaps.defense_pct > 0)].sort_values("t")
    by_team = {tm: g for tm, g in sn.groupby("team")}
    inj = h.inj[h.inj.report_status.isin(["Out", "Doubtful", "Questionable"])]
    inj_by = {k: g for k, g in inj.groupby(["team", "t"])}
    pb = h.pbp_team.sort_values("t") if h.pbp_team is not None else None
    lg = None
    c = {"snaps": by_team, "inj": inj_by, "pbp": pb}
    h._defense_prep = c
    return c


def defense_starters(prep, team: str, tw: int) -> dict[str, tuple[str, str, float]]:
    """{gsis: (name, pos, avg_def_pct)} for players with starter-level defensive snaps over the team's last 4 games."""
    g = prep["snaps"].get(team)
    if g is None:
        return {}
    g = g[g.t < tw]
    last = sorted(g.t.unique())[-4:]
    g = g[g.t.isin(last)]
    avg = g.groupby("gsis").agg(p=("defense_pct", "mean"), pos=("pos", "last"), name=("player", "last"))
    return {k: (r["name"], r["pos"], float(r["p"])) for k, r in avg.iterrows()}


def features_for(h, team: str, opp: str, tw: int, p_abs: dict, statuses_opp=None, statuses_own=None) -> dict:
    """Feature values (+ explanatory pieces) for an offense `team` facing defense `opp` at time tw.
    statuses_*: optional {gsis: (pos, status)} overrides (live use); default = nflverse injury report rows."""
    prep = _prep(h)
    st_opp = defense_starters(prep, opp, tw)
    empty = pd.DataFrame(columns=["gsis", "pos", "report_status", "practice_status"])
    rows_opp = statuses_opp if statuses_opp is not None else {r.gsis: (r.pos, r.report_status, practice_code(r.practice_status)) for r in prep["inj"].get((opp, tw), empty).itertuples()}
    rows_own = statuses_own if statuses_own is not None else {r.gsis: (r.pos, r.report_status, practice_code(r.practice_status)) for r in prep["inj"].get((team, tw), empty).itertuples()}
    n_db = n_rush = 0.0
    names_db, names_rush = [], []
    for gsis, (pos, status, pr) in rows_opp.items():
        if gsis in st_opp:
            nm, spos, pct = st_opp[gsis]
            p = p_for(p_abs, status, pr)
            if spos in DB_POS and pct >= 0.6:
                n_db += p
                names_db.append(f"{nm} ({status})")
            elif spos in RUSH_POS and pct >= 0.5:
                n_rush += p
                names_rush.append(f"{nm} ({status})")
    n_ol = sum(p_for(p_abs, status, pr) for _, (pos, status, pr) in rows_own.items() if pos in OL_POS)
    press = 0.0
    pb = prep["pbp"]
    if pb is not None:
        def trailing(tm, col):
            g = pb[(pb.team == tm) & (pb.t < tw)].tail(4)
            return float(g[col].mean()) if len(g) else np.nan
        lg_made = float(pb[pb.t < tw].press_made.mean()) if (pb.t < tw).any() else np.nan
        lg_all = float(pb[pb.t < tw].press_allowed.mean()) if (pb.t < tw).any() else np.nan
        dm, ta = trailing(opp, "press_made"), trailing(team, "press_allowed")
        if not (np.isnan(dm) or np.isnan(ta) or np.isnan(lg_made) or np.isnan(lg_all)):
            press = ((dm - lg_made) + (ta - lg_all)) * 10      # in tenths of a pressure-rate point
    return {"n_db": n_db, "n_rush": n_rush, "n_ol": float(n_ol), "press": press, "names_db": names_db, "names_rush": names_rush}


class Defense(Module):
    name = "Opposing defense injuries & pass rush"
    kind = "defense"

    def __init__(self, coefs=None, feats=None):
        super().__init__(coefs)
        self.feats = list(feats) if feats else None      # restrict to a subset (used for ablations)

    def _active(self) -> list[str]:
        return self.feats or self.coefs.get("features") or FEATURES

    def _fit_beta(self, F, rows, feats, ridge=200.0) -> dict:
        beta = {}
        for pos in POS:
            m = (rows.pos == pos).to_numpy()
            X = F.loc[m, feats].to_numpy() * rows.base[m].to_numpy()[:, None] / 10
            beta[pos] = ols_through_origin(X, (rows.pts - rows.base)[m].to_numpy(), ridge=ridge).tolist()
        return beta

    def _mae(self, F, rows, beta, feats) -> float:
        delta = np.zeros(len(rows))
        for pos in POS:
            m = (rows.pos == pos).to_numpy()
            if m.any():
                delta[m] = (F.loc[m, feats].to_numpy() * rows.base[m].to_numpy()[:, None] / 10) @ np.array(beta[pos])
        return float(np.abs(rows.pts - rows.base - delta).mean())

    def _feats(self, h, rows) -> pd.DataFrame:
        p_abs = self.coefs.get("p_absent", DEFAULT_P_ABSENT)
        cache: dict = {}
        f = {k: np.zeros(len(rows)) for k in FEATURES}
        nm_db, nm_rush = [""] * len(rows), [""] * len(rows)
        for n, r in enumerate(rows.itertuples()):
            key = (r.team, r.opp, r.t)
            if key not in cache:
                cache[key] = features_for(h, r.team, r.opp, r.t, p_abs)
            v = cache[key]
            for k in FEATURES:
                f[k][n] = v[k]
            nm_db[n], nm_rush[n] = ", ".join(v["names_db"][:2]), ", ".join(v["names_rush"][:2])
        out = pd.DataFrame(f, index=rows.index)
        out["nm_db"], out["nm_rush"] = nm_db, nm_rush
        return out

    def fit(self, h, rows):
        first_eval = int(rows.season.min())
        self.coefs = {"p_absent": estimate_p_absent(h, [s for s in sorted(h.weekly.season.unique()) if s < first_eval])}
        F = self._feats(h, rows)
        feats = self.feats or FEATURES
        if self.feats is None and len(rows) > 400:
            # keep only features that improve MAE on a later slice of the TRAINING data (never touches the held-out season)
            cut = rows.week.median()
            early, late = (rows.week <= cut).to_numpy(), (rows.week > cut).to_numpy()
            base_mae = float(np.abs(rows.pts - rows.base)[late].mean())
            keep = []
            for f in FEATURES:
                beta = self._fit_beta(F[early], rows[early], [f])
                if base_mae - self._mae(F[late], rows[late], beta, [f]) > 0.004:
                    keep.append(f)
            feats = keep or []
        self.coefs["features"] = list(feats)
        self.coefs["beta"] = self._fit_beta(F, rows, list(feats)) if feats else {pos: [] for pos in POS}
        return self

    def predict(self, h, rows):
        out = empty_pred(rows.index)
        F = self._feats(h, rows)
        beta, feats = self.coefs.get("beta", {}), self._active()
        for pos in POS:
            m = (rows.pos == pos).to_numpy()
            if pos in beta and len(beta[pos]) == len(feats) and feats and m.any():
                X = F.loc[m, feats].to_numpy() * rows.base[m].to_numpy()[:, None] / 10
                out.loc[m, "delta"] = X @ np.array(beta[pos])
        reasons = []
        for i, d in zip(rows.index, out["delta"]):
            if abs(d) < 0.25:
                reasons.append("")
                continue
            f = F.loc[i]
            bits = []
            if "n_db" in feats and f.n_db > 0.3:
                bits.append(f"opposing DB(s) out: {f.nm_db}")
            if "n_rush" in feats and f.n_rush > 0.3:
                bits.append(f"pass rusher(s) out: {f.nm_rush}")
            if "n_ol" in feats and f.n_ol > 0.3:
                bits.append(f"{f.n_ol:.1f} of his own OL out")
            if "press" in feats and abs(f.press) > 0.5:
                bits.append("pass-rush vs. protection matchup " + ("favors the defense" if f.press > 0 else "favors the offense"))
            reasons.append("; ".join(bits) + f" → {d:+.1f}")
        out["reason"] = reasons
        out["confidence"] = "low"
        return out
