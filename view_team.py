"""My Team: roster and lineup management (read-only; previews recommended changes)."""
from __future__ import annotations

import streamlit as st

import ui
from ctx import Ctx
from optimizer import availability
from views_common import ai_button, html, player_list

SLOT_ORDER = ["QB", "RB", "WR", "TE", "RB/WR", "WR/TE", "FLEX", "OP", "D/ST", "K"]


def render(ctx: Ctx) -> None:
    me, snap = ctx.me, ctx.snap
    plan = ctx.plan()
    head, tog = st.columns([3, 2], vertical_alignment="center")
    with head:
        html(f'<div class="kpis"><div class="kpi"><b>{plan.current_total:.1f}</b><small>Current projected</small></div>'
             f'<div class="kpi"><b>{plan.optimal_total:.1f}</b><small>Optimal projected</small></div>'
             f'<div class="kpi"><b style="color:{"var(--good)" if plan.gain > 0.05 else "var(--ink)"}">{ui.signed(plan.gain)}</b><small>Possible gain</small></div></div>')
    with tog:
        preview = st.toggle("Preview the optimal lineup", key="team_preview", value=False, disabled=not plan.swaps,
                            help="Shows where each player would sit. Nothing is changed in ESPN." if plan.swaps else "Your lineup is already optimal.")
    html(ui.notice("<b>Fantasy Hub is read-only.</b> Previews show recommendations; make the actual moves in the ESPN app.", "", "lock"))

    rows = plan.optimal if preview else plan.current
    cur_ids = {p.player_id for _, p in plan.current if p}
    opt_ids = {p.player_id for _, p in plan.optimal if p}
    starters = [(slot, p) for slot, p in rows if p]
    start_ids = {p.player_id for _, p in starters}
    empties = [slot for slot, p in rows if p is None]

    html(ui.section("Starters", f"{len(starters)} of {sum(snap.starter_slots.values())} slots filled"))
    items = []
    for slot, p in starters:
        moved = preview and (p.player_id not in cur_ids)
        items.append((p, {"slot": slot, "moved": moved, "note": " · moves into lineup" if moved else ""}))
    player_list(ctx, "starters", items, "No starters set", "Set your lineup in the ESPN app.")
    for slot in empties:
        html(ui.notice(f"Your <b>{ui.esc(slot)}</b> slot is empty.", "bad", "person_off"))

    bench = [p for p in me.roster if p.lineup_slot not in ("IR",) and p.player_id not in start_ids]
    ir = [p for p in me.roster if p.lineup_slot == "IR"]
    html(ui.section("Bench", f"{len(bench)} of {snap.bench_slots} spots"))
    player_list(ctx, "bench", [(p, {"slot": "BN", "moved": preview and p.player_id in cur_ids and p.player_id not in opt_ids,
                                    "note": " · moves to bench" if preview and p.player_id in cur_ids and p.player_id not in opt_ids else ""})
                               for p in sorted(bench, key=lambda p: -availability(p))], "Bench is empty", "")
    if ir or snap.ir_slots:
        html(ui.section("Injured reserve", f"{len(ir)} of {snap.ir_slots} spots"))
        player_list(ctx, "ir", [(p, {"slot": "IR"}) for p in ir], "No one on IR", "")

    if plan.swaps:
        html(ui.section("Recommended changes"))
        for s in plan.swaps:
            html(ui.esc("") + ctx.brand.rec_card(f"{s.player_in.name} in, {s.player_out.name if s.player_out else 'an empty slot'} out", ui.esc(s.reason),
                                                 ic="swap_vert", gain=s.gain, gain_label="proj pts", todo=s.action(),
                                                 players=[s.player_in] + ([s.player_out] if s.player_out else [])))
        ai_button("Explain these changes", "team_explain", "Review my lineup and explain each recommended change simply.", "Lineup review", "fact_check")
