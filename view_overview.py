"""Overview: the weekly manager hub."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

import news as news_mod
import ui
import waivers
from edge.timing import timing_alerts
from ctx import Ctx
from views_common import ai_button, goto_button, html, matchup_state, move_gain


def render(ctx: Ctx) -> None:
    snap, me, opp, b = ctx.snap, ctx.me, ctx.opp, ctx.brand
    plan = ctx.plan()
    m = snap.matchup_for(me.team_id)

    # ---- anchor: matchup scoreboard ----
    if m and opp:
        home = m.home_team_id == me.team_id
        mine, theirs = (m.home_score, m.away_score) if home else (m.away_score, m.home_score)
        mproj, tproj = (m.home_proj, m.away_proj) if home else (m.away_proj, m.home_proj)
        b.prefetch([], [me, opp])
        html(b.scoreboard(me, opp, mine, theirs, mproj, tproj, snap.week, matchup_state(ctx), ui.fresh(ctx.age, ctx.cfg.cache_ttl)))
    else:
        html(ui.empty("No matchup this week", "Your team has a bye or the schedule hasn't loaded.", "event_busy"))

    # ---- lineup readiness / next lock / waivers ----
    starters = [p for p in me.roster if p.lineup_slot not in ("BE", "IR")]
    nxt = sorted((p for p in starters if ui.lock_state(p) == "open"), key=lambda p: ui.kickoff(p))
    ready = not plan.swaps and not plan.warnings
    chips = [ui.chip("Lineup ready" if ready else f"{len(plan.swaps)} lineup change{'s' if len(plan.swaps) != 1 else ''} recommended",
                     "good" if ready else "bad", "check_circle" if ready else "error")]
    if nxt:
        chips.append(ui.chip(f"Next lock: {ui.kick_label(nxt[0])} ({nxt[0].name})", "", "lock_clock"))
    locked = sum(1 for p in starters if ui.lock_state(p) == "locked")
    if locked:
        chips.append(ui.chip(f"{locked} starter{'s' if locked != 1 else ''} locked", "", "lock"))
    open_slots = sum(1 for _, p in plan.current if p is None)
    if open_slots:
        chips.append(ui.chip(f"{open_slots} empty lineup slot{'s' if open_slots != 1 else ''}", "bad", "person_off"))
    if me.waiver_rank:
        chips.append(ui.chip(f"Waiver priority #{me.waiver_rank}", "", "format_list_numbered"))
    if snap.faab_budget:
        chips.append(ui.chip(f"FAAB ${int(snap.faab_budget - me.faab_spent)} left", "", "payments"))
    html(f'<div class="fh-ctx" style="margin-top:14px">{"".join(chips)}</div>')

    # ---- news that changes my lineup (always first) ---------------------------------------
    html(ui.section("News that changes my lineup", ctx.scan_status or "AI reads ESPN news; every item links to its source"))
    mine = {p.player_id: p for p in me.roster}
    blocks = []
    for a in timing_alerts(me.roster, ctx.edge):
        blocks.append(ui.notice(f"<b>{'Re-check before lock' if a['kind'] == 'gtd' else 'Teammate watch'}</b> · {ui.esc(a['message'])}", "warn" if a["severity"] == "watch" else "bad", "schedule"))
    relevant = [ev for ev in ctx.events if ev.get("player_espn_id") in mine and (ev.get("status") or ev.get("event_type") in ("role_change", "depth_chart", "suspension"))]
    blocks += [ui.news_event_html(ev) for ev in relevant[:4]]
    if ctx.edge:
        for c in ctx.edge.cascades:
            for ben in c["beneficiaries"]:
                if ben.get("espn_id") in mine and abs(ben["weekly_pts"]) >= 1.5:
                    applied = ben.get("applied")
                    blocks.append(ui.notice(f"<b>{'Edge' if applied else 'Opportunity context (not in projections)'}:</b> {ui.esc(ben['reason'])}", "", "bolt" if applied else "info"))
                    break
    html("".join(blocks) if blocks else ui.notice("Nothing in the news or injury reports changes your lineup right now.", "good", "check_circle"))
    cb1, cb2, _ = st.columns([2.4, 2.2, 3])
    with cb1:
        if st.button("Re-check injuries & edges", key="ov_recheck", icon=":material/refresh:", help="Re-pulls the NFL injury report, ESPN and Sleeper, then re-runs every edge and the lineup optimizer.", disabled=ctx.demo):
            st.session_state["_force_refresh"] = True
            st.rerun()
    with cb2:
        if relevant or ctx.events:
            ai_button("Summarize news with AI", "ov_news_top", "Summarize the news and injuries affecting my roster this week and what I should do before lock.", "News summary", "newspaper")

    left, right = st.columns([3, 2], gap="large")

    # ---- needs attention ----
    with left:
        html(ui.section("Needs your attention", "from your roster + the value model"))
        cards = 0
        for i, s in enumerate(plan.swaps[:3]):
            cards += 1
            html(b.rec_card(f"Start {s.player_in.name}" + (f" over {s.player_out.name}" if s.player_out else ""), ui.esc(s.reason),
                            ic="swap_vert", tone="act" if s.gain >= 5 else "", gain=s.gain, gain_label="proj pts",
                            why=f"{s.player_in.position} · {s.player_in.pro_team} · {ui.edge_label(s.player_in)}",
                            edge_note=(s.edge_note if s.from_edge else ""),
                            todo=s.action(), players=[s.player_in] + ([s.player_out] if s.player_out else []), feature=(i == 0)))
            c1, c2, _ = st.columns([2, 2, 3])
            with c1:
                goto_button("Open My Team", f"ov_team_{i}", "My Team")
            with c2:
                ai_button("Ask AI why", f"ov_swap_{i}", f"Explain the lineup change: start {s.player_in.name} instead of "
                          f"{s.player_out.name if s.player_out else 'the empty slot'}. Use optimize_lineup and the news.", "Why this lineup change")
        for w in plan.warnings[:2]:
            cards += 1
            html(ui.notice(ui.esc(w), "warn", "warning"))
        try:
            sugg = waivers.suggest_add_drops(snap, ctx.model, ctx.fas, ctx.index, ctx.trending, 2) if ctx.fas else []
        except Exception:
            sugg = []
        for i, s in enumerate(sugg[:1]):
            cards += 1
            html(b.rec_card(f"Add {s.add.name}, drop {s.drop.name}", ui.esc(s.reason), ic="person_add", gain=move_gain(s)[0], gain_label=move_gain(s)[1],
                            why=f"{s.add.position} · {s.add.pro_team}" + (" · trending on Sleeper" if s.trending_adds else ""), todo=s.action(),
                            players=[s.add]))
            c1, c2, _ = st.columns([2, 2, 3])
            with c1:
                goto_button("See waivers", f"ov_wv_{i}", "Players")
            with c2:
                ai_button("Ask AI why", f"ov_add_{i}", f"Should I add {s.add.name} and drop {s.drop.name}? Use suggest_waiver_moves and news.", "Waiver move review")
        if not cards:
            html(ui.notice("<b>Nothing urgent.</b> Your lineup is set and no waiver move is clearly worth making.", "good", "check_circle"))


    # ---- standings snapshot ----
    with right:
        html(ui.section("League standing"))
        ordered = snap.standings()
        idx = next((i for i, t in enumerate(ordered) if t.team_id == me.team_id), 0)
        window = ordered[max(0, idx - 2): idx + 3]
        b.prefetch([], window)
        rows = "".join(
            f'<div class="row" style="grid-template-columns:auto 1fr auto;{"background:var(--hover);" if t.team_id == me.team_id else ""}">'
            f'<span class="num" style="width:22px;font-weight:700;color:var(--ink-3)">{t.standing}</span>'
            f'<div class="who">{b.team_avatar(t, 34)}<div style="min-width:0"><div class="nm">{ui.esc(t.name)}</div><div class="sub">{ui.esc(t.owner_label)}</div></div></div>'
            f'<div class="stat"><b>{ui.esc(t.record)}</b><small>{t.points_for:.0f} PF</small></div></div>' for t in window)
        html(f'<div class="rows solid">{rows}</div>')
        goto_button("Full league", "ov_league", "League", "leaderboard")
        html(ui.section("Your week at a glance"))
        top = sorted(starters, key=lambda p: -p.week_proj)[:3]
        html("".join(f'<div style="display:flex;align-items:center;gap:12px;padding:6px 0">{b.avatar(p, 40)}<div style="min-width:0"><div class="nm" style="font-weight:600">'
                     f'{ui.esc(p.name)}</div><div class="fresh">{p.position} · {ui.esc(p.opponent and "vs " + p.opponent or "Bye")}</div></div>'
                     f'<div style="margin-left:auto" class="kpi"><b>{p.week_proj:.1f}</b><small>Proj</small></div></div>' for p in top) or ui.empty("No starters set", "", "groups"))
        ai_button("Review my whole lineup", "ov_lineup", "Review my lineup for this week: who to start and sit and why.", "Lineup review", "fact_check")
