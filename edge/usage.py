"""Usage & opportunity metrics for a player (from nflverse): snap share, target/carry share, volume and expected-vs-actual points."""
from __future__ import annotations

from typing import Optional

import numpy as np


def usage_summary(h, gsis: str, season: int, tw: int) -> dict:
    """Season-to-date numbers for the games before `tw`. Missing data -> missing keys (never guessed)."""
    out: dict = {}
    w = h.weekly[(h.weekly.gsis == gsis) & (h.weekly.season == season) & (h.weekly.t < tw)]
    if w.empty:
        return out
    g = len(w)
    out["games"] = g
    if w.targets.sum() > 0 or w.carries.sum() > 0:
        out["targets_pg"], out["carries_pg"] = float(w.targets.mean()), float(w.carries.mean())
    if "target_share" in w and w.target_share.notna().any():
        out["target_share"] = float(w.target_share.mean())
    # carry share of the team's carries, from per-game team totals
    team_c = h.weekly[(h.weekly.season == season) & (h.weekly.t < tw)].groupby(["team", "t"]).carries.sum()
    if w.carries.sum() > 0:
        tot = [team_c.get((r.team, r.t), np.nan) for r in w.itertuples()]
        out["carry_share"] = float(np.nanmean([r.carries / t if t else np.nan for r, t in zip(w.itertuples(), tot)]))
    s = h.snaps[(h.snaps.gsis == gsis) & (h.snaps.season == season) & (h.snaps.t < tw) & (h.snaps.offense_pct > 0)].sort_values("t")
    if len(s):
        out["snap_share"] = float(s.offense_pct.mean())
        if len(s) >= 2:
            out["snap_share_last2"] = float(s.offense_pct.tail(2).mean())
    rz = getattr(h, "rz", None)
    if rz is not None and len(rz):
        r = rz[(rz.gsis == gsis) & (rz.season == season) & (rz.t < tw)]
        gp = g
        out["rz_touch_pg"] = float((r.rz_carries.sum() + r.rz_targets.sum()) / gp)
        out["gl_touch_pg"] = float((r.gl_carries.sum() + r.gl_targets.sum()) / gp)
    x = h.xfp[(h.xfp.gsis == gsis) & (h.xfp.season == season) & (h.xfp.t < tw)]
    if len(x):
        out["xfp_pg"], out["actual_pg"] = float(x.xfp.mean()), float(x.xfp_actual.mean())
    return out


def usage_cells(u: dict, pos: str) -> list[tuple[str, str, str]]:
    """(value, label, hint) tuples for display."""
    cells = []
    if "snap_share" in u:
        last = f" · last 2: {u['snap_share_last2'] * 100:.0f}%" if "snap_share_last2" in u else ""
        cells.append((f"{u['snap_share'] * 100:.0f}%", "Snap share", f"share of offensive plays{last}"))
    if pos in ("WR", "TE", "RB") and "targets_pg" in u:
        sh = f" · {u['target_share'] * 100:.0f}% of team targets" if "target_share" in u else ""
        cells.append((f"{u['targets_pg']:.1f}", "Targets / game", f"passes thrown his way{sh}"))
    if pos in ("RB", "QB") and u.get("carries_pg", 0) >= 1:
        sh = f" · {u['carry_share'] * 100:.0f}% of team carries" if "carry_share" in u else ""
        cells.append((f"{u['carries_pg']:.1f}", "Carries / game", f"rushing attempts{sh}"))
    if "rz_touch_pg" in u and pos in ("RB", "WR", "TE", "QB"):
        cells.append((f"{u['rz_touch_pg']:.1f}", "Red-zone touches / game", f"carries + targets inside the 20 · inside the 5: {u['gl_touch_pg']:.1f} (the opportunities touchdowns come from)"))
    if "xfp_pg" in u:
        cells.append((f"{u['xfp_pg']:.1f} vs {u['actual_pg']:.1f}", "Expected vs actual pts", "points his opportunities were worth vs what he scored (per game)"))
    return cells
