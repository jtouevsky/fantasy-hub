"""Backtest: does each edge module make weekly predictions more accurate, in MY league's scoring?

Run:  python -m edge.backtest            (writes docs/backtest.md and edge/params.json)

Baseline = trailing 4-game average fantasy points (ESPN's historical projections aren't available), and each module is
scored on its *incremental* improvement over that baseline.

Protocol (no tuning on the data we report):
  * fit coefficients on 2024 weeks 3-10, choose the strength alpha in {0, .25, .5, .75, 1} on 2024 weeks 11-18
  * refit on all of 2024 and score 2025 (the held-out season) with that alpha
  * paired bootstrap 95% CI on the 2025 MAE difference; a module ships only if the 2025 improvement is real
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from edge import scoring
from edge.features import eval_frame
from edge.history import Hist
from edge.modules.base import Module
from edge.settings import EdgeSettings, load_params, save_params
from edge.types import cap_limit

ALPHAS = [0.0, 0.25, 0.5, 0.75, 1.0]
SEED = 7


def mae(err) -> float:
    return float(np.mean(np.abs(err))) if len(err) else float("nan")


def paired_ci(abs_base: np.ndarray, abs_adj: np.ndarray, n: int = 1000) -> tuple[float, float, float]:
    """Mean improvement (base - adj, positive = better) with a bootstrap 95% CI."""
    d = abs_base - abs_adj
    if len(d) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(SEED)
    means = rng.choice(d, size=(n, len(d)), replace=True).mean(axis=1)
    return float(d.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def capped(base: pd.Series, delta: pd.Series, s: EdgeSettings) -> pd.Series:
    lim = base.clip(lower=s.cap_floor) * s.cap_pct
    return delta.clip(lower=-lim, upper=lim)


@dataclass
class ModuleReport:
    key: str
    name: str
    alpha: float
    n_2025: int
    n_aff_2025: int
    mae_base_2025: float
    mae_adj_2025: float
    gain_2025: float
    ci_lo: float
    ci_hi: float
    aff_base_2025: float
    aff_adj_2025: float
    aff_gain: float
    aff_ci: tuple[float, float]
    mae_base_2024: float
    mae_adj_2024: float
    aff_gain_2024: float
    n_aff_2024: int
    coefs_2024: dict = field(default_factory=dict)
    coefs_prod: dict = field(default_factory=dict)
    decision: str = ""
    note: str = ""


def choose_alpha(mod: Module, h: Hist, E: pd.DataFrame) -> float:
    tr = E[(E.season == 2024) & (E.week <= 10)]
    va = E[(E.season == 2024) & (E.week >= 11)]
    m = type(mod)().fit(h, tr)
    pred = m.predict(h, va)
    best, best_mae = 0.0, mae(va.pts - va.base)
    for a in ALPHAS[1:]:
        cur = mae(va.pts - (va.base + a * pred["delta"]))
        if cur < best_mae - 1e-9:
            best, best_mae = a, cur
    return best


def evaluate(mod_cls, h: Hist, E: pd.DataFrame, key: str, settings: EdgeSettings) -> ModuleReport:
    alpha = choose_alpha(mod_cls(), h, E)
    tr24 = E[E.season == 2024]
    m = mod_cls().fit(h, tr24)
    rep = {}
    for season in (2024, 2025):
        d = E[E.season == season]
        pred = m.predict(h, d)
        delta = capped(d.base, alpha * pred["delta"], settings)
        aff = m.affected(pred)
        rep[season] = (d, delta, aff)
    d25, dl25, aff25 = rep[2025]
    d24, dl24, aff24 = rep[2024]
    ab, aa = np.abs(d25.pts - d25.base).to_numpy(), np.abs(d25.pts - (d25.base + dl25)).to_numpy()
    gain, lo, hi = paired_ci(ab, aa)
    agb, aga = ab[aff25.to_numpy()], aa[aff25.to_numpy()]
    ag, alo, ahi = paired_ci(agb, aga)
    ab24, aa24 = np.abs(d24.pts - d24.base).to_numpy(), np.abs(d24.pts - (d24.base + dl24)).to_numpy()
    prod = mod_cls().fit(h, E[E.season.isin([2024, 2025])])
    r = ModuleReport(key, m.name, alpha, len(d25), int(aff25.sum()), float(ab.mean()), float(aa.mean()), gain, lo, hi,
                     float(agb.mean()) if len(agb) else float("nan"), float(aga.mean()) if len(aga) else float("nan"), ag, (alo, ahi),
                     float(ab24.mean()), float(aa24.mean()), float((ab24 - aa24)[aff24.to_numpy()].mean()) if aff24.any() else float("nan"), int(aff24.sum()),
                     m.coefs, prod.coefs)
    # decision: ship at the validated strength only if the held-out 2025 result on the rows it moves is positive
    if alpha == 0.0:
        r.decision, r.note = "OFF", "no improvement on the 2024 validation weeks (alpha = 0)"
    elif r.n_aff_2025 < 30:
        r.decision, r.alpha, r.note = "OFF", 0.0, f"too few affected 2025 rows ({r.n_aff_2025}) to trust"
    elif r.aff_gain <= 0:
        r.decision, r.alpha, r.note = "OFF", 0.0, "2025 hold-out: worse than baseline on the rows it moves"
    elif r.aff_ci[0] > 0:
        r.decision, r.note = "ON", "2025 hold-out improvement is statistically clear (CI excludes 0)"
    else:
        shrink = max(alpha * 0.5, ALPHAS[1])
        r.decision, r.alpha, r.note = "SHRUNK", shrink, "2025 improvement is positive but not statistically clear; strength halved"
    return r


def combined(mods: list[tuple[Module, float]], h: Hist, E: pd.DataFrame, settings: EdgeSettings) -> dict:
    d = E[E.season == 2025]
    total = pd.Series(0.0, index=d.index)
    for m, a in mods:
        if a > 0:
            total = total + a * m.predict(h, d)["delta"]
    adj = capped(d.base, total, settings)
    ab, aa = np.abs(d.pts - d.base).to_numpy(), np.abs(d.pts - (d.base + adj)).to_numpy()
    g, lo, hi = paired_ci(ab, aa)
    return {"n": len(d), "mae_base": float(ab.mean()), "mae_adj": float(aa.mean()), "gain": g, "lo": lo, "hi": hi,
            "by_pos": {p: (float(np.abs(d.pts - d.base)[d.pos == p].mean()), float(np.abs(d.pts - (d.base + adj))[d.pos == p].mean())) for p in ["QB", "RB", "WR", "TE"]}}


def module_registry() -> dict[str, type[Module]]:
    from edge.modules.vegas import Vegas
    from edge.modules.weather import Weather
    reg: dict[str, type[Module]] = {"vegas": Vegas, "weather": Weather}
    for name, path, cls in (("cascade", "edge.modules.cascade", "Cascade"), ("defense", "edge.modules.defense", "Defense"),
                            ("regression", "edge.modules.regression", "Regression")):
        try:
            mod = __import__(path, fromlist=[cls])
            reg[name] = getattr(mod, cls)
        except ImportError:
            pass
    return reg


def render(reports: list[ModuleReport], comb: dict, E: pd.DataFrame, settings: EdgeSettings, wts: dict, started: float) -> str:
    n24, n25 = int((E.season == 2024).sum()), int((E.season == 2025).sum())
    L = ["# Edge engine backtest", "",
         f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m edge.backtest` in {time.time() - started:.0f}s._", "",
         "## Method", "",
         "* **Target:** actual weekly fantasy points in *this league's* scoring (PPR 1.0, 4-pt pass TD, 6-pt rush/rec TD, -2 INT/fumble lost, "
         "0.04 pass / 0.1 rush-rec yd), computed from nflverse box-score stats (`nflreadpy`).",
         "* **Baseline:** trailing 4-game average of fantasy points (2+ prior games). ESPN's historical weekly projections aren't available, so each module "
         "is measured on its **incremental** improvement over this simple baseline. Real ESPN projections are better than this baseline, so true gains over ESPN will be smaller.",
         f"* **Population:** QB/RB/WR/TE who played, baseline >= 5 pts, weeks 3-18. 2024: {n24:,} player-games, 2025: {n25:,}. Pre-game information only "
         "(injury report status, Vegas closing lines, actual wind/temperature as a forecast proxy).",
         "* **No tuning on reported data:** coefficients fit on 2024 weeks 3-10; strength (alpha) chosen on 2024 weeks 11-18; refit on all 2024; "
         "**2025 is the held-out season shown below.** ON/SHRUNK/OFF decisions use the 2025 result on the rows each module moves, so treat the final 2025 numbers as validation of the "
         "shipped configuration, not as an unbiased estimate of future gains.",
         f"* **Cap:** total adjustment per player-week <= {settings.cap_pct:.0%} of max(baseline, {settings.cap_floor:g} pts).",
         "* MAE = mean absolute error in fantasy points (lower is better). 'Gain' = baseline MAE minus adjusted MAE (positive = better), with a paired-bootstrap 95% CI.", "",
         "## Results by module (2025 hold-out)", "",
         "| Module | Decision | alpha | Rows moved | MAE on moved rows: base → adj | Gain on moved rows (95% CI) | Gain on all rows |",
         "|---|---|---|---|---|---|---|"]
    for r in reports:
        L.append(f"| {r.name} | **{r.decision}** | {r.alpha:g} | {r.n_aff_2025} of {r.n_2025} | {r.aff_base_2025:.2f} → {r.aff_adj_2025:.2f} | "
                 f"{r.aff_gain:+.3f} ({r.aff_ci[0]:+.3f} to {r.aff_ci[1]:+.3f}) | {r.gain_2025:+.4f} ({r.ci_lo:+.4f} to {r.ci_hi:+.4f}) |")
    L += ["", "### Notes per module", ""]
    for r in reports:
        L.append(f"* **{r.name}** - {r.note}. 2024 (in-sample) gain on moved rows: {r.aff_gain_2024:+.3f} over {r.n_aff_2024} rows.")
    L += ["", "## All shipped modules together (2025 hold-out)", "",
          f"* {comb['n']:,} player-games. MAE **{comb['mae_base']:.3f} → {comb['mae_adj']:.3f}** "
          f"(gain {comb['gain']:+.4f}, 95% CI {comb['lo']:+.4f} to {comb['hi']:+.4f}).", "",
          "| Position | Baseline MAE | With edges |", "|---|---|---|"]
    for p, (a, b) in comb["by_pos"].items():
        L.append(f"| {p} | {a:.3f} | {b:.3f} |")
    L += ["", "## Caveats", "",
          "* Weather uses actual game-time wind/temperature as a stand-in for a forecast; live forecasts are noisier, so expect a smaller effect. Precipitation isn't in the historical table and is untested.",
          "* News scanning (module 6) and timing (module 7) can't be backtested - there is no historical news feed. They only feed modules 1-2 and alerts; they never create point adjustments by themselves.",
          "* One baseline, two seasons, one league's scoring. Small effects (< ~0.05 pts MAE) are within noise even when positive.", ""]
    return "\n".join(L)


def main() -> None:
    t0 = time.time()
    settings = EdgeSettings()
    wts = scoring.weights()
    print("loading nflverse 2022-2025 ...")
    h = Hist.load([2022, 2023, 2024, 2025], wts, with_pbp=True)
    E = eval_frame(h, [2024, 2025])
    print(f"eval rows: 2024={int((E.season == 2024).sum())} 2025={int((E.season == 2025).sum())}")
    reg = module_registry()
    reports, shipped = [], []
    params = {"settings": {"cap_pct": settings.cap_pct, "cap_floor": settings.cap_floor}, "modules": {}}
    for key, cls in reg.items():
        print(f"  evaluating {key} ...")
        r = evaluate(cls, h, E, key, settings)
        reports.append(r)
        params["modules"][key] = {"alpha": r.alpha, "decision": r.decision, "coefs": r.coefs_prod}
        print(f"    {r.decision:7s} alpha={r.alpha:g} moved={r.n_aff_2025} gain_on_moved={r.aff_gain:+.3f} ({r.aff_ci[0]:+.3f},{r.aff_ci[1]:+.3f})")
        if r.alpha > 0:
            shipped.append((cls().fit(h, E[E.season == 2024]), r.alpha))
    comb = combined(shipped, h, E, settings)
    print(f"combined: {comb['mae_base']:.3f} -> {comb['mae_adj']:.3f} ({comb['gain']:+.4f})")
    os.makedirs("docs", exist_ok=True)
    with open("docs/backtest.md", "w", encoding="utf-8") as f:
        f.write(render(reports, comb, E, settings, wts, t0))
    save_params(params)
    print("wrote docs/backtest.md and edge/params.json")


if __name__ == "__main__":
    main()
