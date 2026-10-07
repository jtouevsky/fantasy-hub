"""More: News feed and the recommendation log."""
from __future__ import annotations

import time

import streamlit as st

import db
import news as news_mod
import ui
from ctx import Ctx
from views_common import ai_button, html, player_list


def _news(ctx: Ctx) -> None:
    fetch = ctx.news_fetch()
    if fetch is None:
        html(ui.empty("News isn't available in demo mode", "Connect your league to see ESPN and Sleeper news.", "newspaper"))
        return
    me, opp, snap = ctx.me, ctx.opp, ctx.snap
    teams = [("My team", me)] + ([("Opponent", opp)] if opp else [])
    slot = st.empty()
    slot.html(ui.skeleton(4, 54))
    try:
        data = {t.team_id: news_mod.collect_team_news(t, fetch, ctx.index, ctx.cfg.db_path) for _, t in teams}
    except Exception as e:
        slot.html(ui.notice(f"News couldn't be loaded ({type(e).__name__}). Try Refresh.", "warn", "cloud_off"))
        return
    slot.empty()
    html(ui.section("Lineup alerts", "things that should change this week's lineup"))
    any_alert = False
    for label, t in teams:
        for a in news_mod.lineup_alerts(snap, t, data[t.team_id]):
            any_alert = True
            who = "" if label == "My team" else f"{ui.esc(t.name)}: "
            html(ui.notice(f"<b>{a.severity.title()}</b> · {who}{ui.esc(a.message)}" + (f"<br><small>{ui.esc(a.action)}</small>" if a.action and label == "My team" else ""),
                           {"ACT": "bad", "WATCH": "warn", "INFO": ""}[a.severity], {"ACT": "error", "WATCH": "visibility", "INFO": "info"}[a.severity]))
    if not any_alert:
        html(ui.notice("Nothing in the news should change your lineup this week.", "good", "check_circle"))
    ai_button("Summarize with AI", "news_sum", "Summarize news and injuries affecting my roster and my opponent's roster, and what it means for my lineup.", "News summary", "newspaper")
    for label, t in teams:
        html(ui.section(f"{label}: {t.name}"))
        for p in t.roster:
            pn = data[t.team_id][p.player_id]
            if not pn.items and not pn.injury_line:
                continue
            with st.expander(f"{p.name} · {p.position} · {p.pro_team}" + (f" · {p.injury_status.title().replace('_', ' ')}" if p.injury_status != 'ACTIVE' else "")):
                if pn.injury_line:
                    html(ui.notice(f"Sleeper: {ui.esc(pn.injury_line)}", "warn", "medical_services"))
                for it in pn.items[:4]:
                    html(f'<div class="news"><b>{ui.esc(it.headline)}</b><p>{ui.esc(it.story[:420])}</p><small>{ui.esc(it.source)} · {ui.esc(it.published[:10])}</small></div>')


def _log(ctx: Ctx) -> None:
    rows = db.list_recommendations(200, ctx.cfg.db_path)
    if not rows:
        html(ui.empty("No recommendations saved yet", "Advice from the AI, and trades you save, will collect here so you can check later whether they worked.", "bookmark"))
        return
    html(ui.section("Recommendation log", "mark outcomes to learn what works"))
    for r in rows[:60]:
        when = time.strftime("%b %-d, %-I:%M %p", time.localtime(r["created_at"]))
        html(f'<div class="news"><div class="fh-ctx">{ui.chip(r["kind"].title(), "pos")}{ui.chip(r["source"].upper(), "ai" if r["source"] == "agent" else "")}'
             f'{ui.chip(r["outcome"], "good", "flag") if r["outcome"] else ""}<span class="fresh">Week {r["week"] or "-"} · {when}</span></div><p>{ui.esc(r["summary"][:420])}</p></div>')
    with st.form("outcome"):
        c1, c2, c3 = st.columns([1, 3, 1], vertical_alignment="bottom")
        rid = c1.number_input("Entry ID", min_value=1, step=1, value=int(rows[0]["id"]))
        out = c2.text_input("Outcome", placeholder="Worked: won by 12 · Didn't work: he got hurt · Ignored")
        if c3.form_submit_button("Save outcome") and out:
            db.set_outcome(int(rid), out, ctx.cfg.db_path)
            st.rerun()
    ids = ", ".join(str(r["id"]) for r in rows[:10])
    html(f'<div class="fresh">Latest entry IDs: {ids}</div>')


def render(ctx: Ctx) -> None:
    sel = st.segmented_control("More", ["News", "Recommendation log"], default="News", key="more_sel", label_visibility="collapsed") or "News"
    (_news if sel == "News" else _log)(ctx)
