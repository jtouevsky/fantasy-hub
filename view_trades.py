"""Trades: find and evaluate deals, shown as readable two-sided offers."""
from __future__ import annotations

import streamlit as st

import db
import trades
import ui
from ctx import Ctx
from views_common import ai_button, html

_ACC = {"Likely": ("good", "thumb_up"), "Maybe": ("warn", "help"), "Unlikely": ("bad", "thumb_down")}


def _side(b, players) -> str:
    return "".join(f'<div class="p" style="--tc:{b.color(p.pro_team)}">{b.avatar(p, 40)}<div style="min-width:0"><div class="nm">{ui.esc(p.name)}</div>'
                   f'<div class="sub">{ui.chip(p.position, "pos")} {ui.esc(p.pro_team)}{" · " + p.injury_status.replace("_", " ").title() if p.injury_status != "ACTIVE" else ""}{ui.tag_chips(p)}</div></div></div>'
                   for p in players)


def _impact(label: str, imp) -> str:
    d = imp.delta
    detail = []
    if imp.now_starting: detail.append(", ".join(imp.now_starting) + " would start")
    if imp.no_longer_starting: detail.append(", ".join(imp.no_longer_starting) + " to the bench")
    if imp.pickups_needed: detail.append("needs a free " + "/".join(imp.pickups_needed) + " pickup")
    return f'<div><b>{ui.esc(label)}</b><span class="d num {"up" if d > 0.05 else "dn" if d < -0.05 else ""}">{d:+.1f}</span> pts/week<br>{ui.esc("; ".join(detail)) or "No change to the starting lineup."}</div>'


def offer_card(ctx: Ctx, ev: trades.TradeEval) -> str:
    b = ctx.brand
    tone, ic = _ACC[ev.acceptance]
    notes = "".join(f'<div class="fresh" style="margin-top:6px">{ui.icon("info")}{ui.esc(n)}</div>' for n in ev.notes)
    return (f'<article class="offer glass-med"><div class="fh-ctx" style="margin-bottom:12px">{ui.chip(ev.kind, "pos")}'
            f'{ui.chip("Other manager: " + ev.acceptance + " to accept", tone, ic)}</div>'
            f'<div class="sides"><div class="col"><h5>You give</h5>{_side(b, ev.give)}</div><div class="swap">{ui.icon("swap_horiz")}</div>'
            f'<div class="col"><h5>You get from {ui.esc(ev.other_team)}</h5>{_side(b, ev.get)}</div></div>'
            f'<div class="meter"><div class="lbl"><span>You {ev.my_share:.0f}</span><span style="color:var(--ink-3)">{ev.their_share:.0f} Them</span></div>'
            f'<div class="track" role="img" aria-label="Value split {ev.my_share:.0f} to {ev.their_share:.0f} in your favor"><i style="width:{ev.my_share:.0f}%"></i></div></div>'
            f'<div class="impact">{_impact("Your lineup", ev.mine)}{_impact(ev.other_team + "\'s lineup", ev.theirs)}</div>{notes}'
            f'<div class="todo">{ui.icon("arrow_forward")}<span>Do this in the ESPN app: open {ui.esc(ev.other_team)}\'s team and propose this trade.</span></div>'
            f'<div class="fresh" style="margin-top:8px">Estimate from a simple value model (points above replacement, plus lineup impact). It cannot know how the other manager feels.</div></article>')


def _prompt(ev: trades.TradeEval) -> str:
    return (f"Evaluate this trade for me: I give {' + '.join(p.name for p in ev.give)} and get {' + '.join(p.name for p in ev.get)} "
            f"from {ev.other_team}. Use evaluate_trade, explain in plain English, and tell me whether to propose it.")


def _show(ctx: Ctx, ev: trades.TradeEval, key: str) -> None:
    ctx.brand.prefetch(ev.give + ev.get)
    html(offer_card(ctx, ev))
    c1, c2, _ = st.columns([2.4, 2, 3])
    with c1:
        ai_button("Ask AI about this", f"tr_{key}", _prompt(ev), "Trade review", "balance")
    with c2:
        if st.button("Save to log", key=f"log_{key}", icon=":material/bookmark_add:"):
            db.log_recommendation("trade", f"{' + '.join(p.name for p in ev.give)} for {' + '.join(p.name for p in ev.get)} ({ev.other_team})",
                                  {"split": [ev.my_share, ev.their_share], "acceptance": ev.acceptance}, ctx.snap.week, "ui", ctx.cfg.db_path)
            st.toast("Saved to your recommendation log.")


def render(ctx: Ctx) -> None:
    snap, me = ctx.snap, ctx.me
    others = [t for t in snap.teams if t.team_id != me.team_id]
    label = lambda t: f"{t.owners[0].first_name} · {t.name}" if t.owners and t.owners[0].first_name else t.name
    labels = {label(t): t for t in others}
    ctx.brand.prefetch([], others)
    mode = st.segmented_control("Mode", ["Find me a trade", "Evaluate a deal"], default="Find me a trade", key="tr_mode", label_visibility="collapsed")
    if "trade_partner" in st.session_state and st.session_state["trade_partner"] not in labels:
        st.session_state.pop("trade_partner")
    other = labels[st.selectbox("Trade with", list(labels), key="trade_partner", help="Search by owner first name or team name.")]
    html(f'<div class="fh-ctx">{ctx.brand.team_avatar(other, 28)}<b>{ui.esc(other.name)}</b>{ui.chip(other.record, "", "sports_score")}{ui.chip(other.owner_label or "Owner unknown", "", "person")}</div>')
    pl = lambda p: f"{p.name} · {p.position} · {p.pro_team}"
    mine = {pl(p): p for p in sorted(me.roster, key=lambda p: -ctx.model.value(p))}
    theirs = {pl(p): p for p in sorted(other.roster, key=lambda p: -ctx.model.value(p))}

    if mode == "Evaluate a deal":
        c1, c2 = st.columns(2)
        give = c1.multiselect("You give", list(mine), key="ev_give", placeholder="Choose your players")
        get = c2.multiselect(f"You get", list(theirs), key="ev_get", placeholder=f"Choose from {other.name}")
        if give and get:
            _show(ctx, trades.evaluate_trade(snap, ctx.model, other, [mine[g] for g in give], [theirs[g] for g in get]), "eval")
        else:
            html(ui.empty("Pick players on both sides", "I'll show the value split and how each lineup changes.", "swap_horiz"))
        return

    c1, c2, c3 = st.columns([3, 2, 2])
    offer = c1.selectbox("Player you're offering", list(mine), index=None, key="find_offer", placeholder="Choose a player to trade away")
    split = c2.slider("Target split in your favor", 50, 70, 60, key="find_split", help="60 means you get 60% of the combined value.")
    want = c3.multiselect("Only ask for", sorted({p.position for p in other.roster}), key="find_want", placeholder="Any position")
    if not offer:
        html(ui.empty("Choose who you'd trade away", "I'll search 1-for-1, 2-for-1 and 1-for-2 packages and rank deals the other manager might actually accept.", "swap_horiz"))
        return
    found = trades.find_trades(snap, ctx.model, other, [mine[offer]], float(split), set(want) or None, 6)
    if not found:
        html(ui.notice("No reasonable package near that split. Try a lower target or remove the position filter.", "warn", "search_off"))
        return
    html(ui.section(f"{len(found)} options", "best first"))
    for i, ev in enumerate(found):
        _show(ctx, ev, f"f{i}")
