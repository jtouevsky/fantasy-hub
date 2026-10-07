"""More: News feed and the recommendation log."""
from __future__ import annotations

import time

import streamlit as st

import db
import news as news_mod
import strategy as strategy_mod
from edge.settings import load_params
from edge import odds as odds_mod
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


def _edge_engine(ctx: Ctx) -> None:
    e = ctx.edge
    if e is None:
        html(ui.empty("The edge engine isn't running", "Demo data has no real player IDs; with a real league it runs automatically. If this is your league, check the warnings at the top of the page.", "bolt"))
        return
    params = load_params()
    html(ui.section("How it works"))
    html(ui.notice("Every number starts with <b>ESPN's projection</b>. Edges add or subtract points for specific, explainable reasons; each adjustment is stored with its source and confidence, "
                   "total movement is capped per player, and if data is missing nothing is adjusted. Strengths below come from a backtest on 2024-2025 (see docs/backtest.md).", "", "bolt"))
    s = params.get("summary")
    if s:
        html(f'<div class="kpis"><div class="kpi"><b>{s["mae_base"]:.2f} → {s["mae_adj"]:.2f}</b><small>Typical weekly miss (pts), 2025 hold-out</small></div>'
             f'<div class="kpi"><b>{s["gain_lo"]:+.2f} to {s["gain_hi"]:+.2f}</b><small>95% CI of the improvement</small></div></div>')
        html('<div class="fresh">Measured against a simple trailing-average baseline (ESPN history isn\'t available), so gains over real ESPN projections will be smaller.</div>')
    html(ui.section("Modules"))
    live = params.get("live_scale", {})
    names = {"vegas": "Game environment (Vegas)", "weather": "Weather", "cascade": "Injury cascade", "defense": "Opposing defense / own OL injuries", "regression": "Opportunity vs. production"}
    rows = "".join(f'<tr><td>{ui.esc(names.get(k, k))}</td><td>{ui.chip(v.get("decision", "?"), "good" if v.get("decision") == "ON" else "warn" if v.get("decision") == "SHRUNK" else "")}</td>'
                   f'<td class="num">{v.get("alpha", 0):g}</td><td class="num">x{live.get(k, 1):g}</td></tr>' for k, v in params.get("modules", {}).items())
    html(f'<div class="solid" style="border-radius:18px;padding:8px 12px"><table class="edge-table"><tr><th>Module</th><th>Backtest verdict</th><th>Strength</th><th>Live haircut</th></tr>{rows}</table></div>'
         '<div class="fresh" style="margin-top:6px">Live haircuts are judgment calls: ESPN already absorbs part of these signals. News scanning (AI) and timing alerts are not backtestable and only drive alerts/injury status.</div>')
    html(ui.section("Data sources right now"))
    ds = dict(e.data_status)
    q = odds_mod.quota(ctx.cfg.db_path)
    if q["remaining"]:
        ds["odds_quota"] = f"The Odds API credits remaining: {q['remaining']}"
    html("".join(ui.notice(f"<b>{ui.esc(k.replace('_', ' '))}:</b> {ui.esc(v)}", "", "database") for k, v in ds.items()))
    if ctx.scan_status:
        html(ui.notice(f"<b>AI news scan:</b> {ui.esc(ctx.scan_status)}", "", "auto_awesome"))
    html(ui.section("Injury cascades in effect", "who is out, and who picks up the work"))
    shown = 0
    for c in sorted(e.cascades, key=lambda c: -max((abs(b["weekly_pts"]) for b in c["beneficiaries"]), default=0))[:8]:
        absent = ", ".join(f'{a["name"]} ({a["status"]}{", long-term" if a["long_term"] else ""}; p(out) {a["p_out"]:.0%})' for a in c["absent"][:4])
        top = sorted(c["beneficiaries"], key=lambda b: -abs(b["weekly_pts"]))[:3]
        html(f'<div class="news"><b>{ui.esc(c["team"])}</b> · {ui.esc(absent)}' + "".join(f'<p>{ui.esc(b["reason"])}</p>' for b in top) + "</div>")
        shown += 1
    if not shown:
        html(ui.notice("No skill-position absences are creating cascades this week.", "", "check_circle"))
    html(ui.section("Biggest adjustments this week"))
    pls = [p for t in ctx.snap.teams for p in t.roster] + list(ctx.fas)
    adj = sorted((p for p in pls if p.has_edge), key=lambda p: -abs(p.edge_total))[:25]
    body = "".join(f'<tr><td><b>{ui.esc(p.name)}</b><br><small>{p.position} · {ui.esc(p.pro_team)}</small></td><td class="num">{ui.edge_label(p)}</td>'
                   f'<td>{ui.esc(max(p.edge, key=lambda a: abs(a["delta"]))["reason"])}</td></tr>' for p in adj)
    html(f'<div class="solid" style="border-radius:18px;padding:8px 12px"><table class="edge-table"><tr><th>Player</th><th>Projection</th><th>Biggest reason</th></tr>{body}</table></div>' if adj else ui.notice("No adjustments this week.", "", "info"))
    html(ui.section("Game environments"))
    envs = {frozenset((x.team, x.opp)): x for x in e.game_env.values()}
    html("".join(f'<div style="margin:6px 0"><b>{ui.esc(x.team)} vs {ui.esc(x.opp)}</b> <span class="fresh">{ui.esc(x.kickoff)}</span>{ui.game_env_html(x)}</div>' for x in envs.values()) or ui.notice("No schedule rows.", "", "info"))
    if ctx.events:
        html(ui.section("AI-parsed news this week", f"{len(ctx.events)} events"))
        html("".join(ui.news_event_html(ev) for ev in ctx.events[:10]))


def _strategy(ctx: Ctx) -> None:
    cur = ctx.hub.strategy
    html(ui.notice("These rules apply to <b>every</b> recommendation: the Waivers page, Overview cards, the lineup optimizer and the AI assistant all use them. "
                   "Nothing here changes anything on ESPN.", "", "tune"))
    slots = ctx.snap.starter_slots
    with st.form("strategy_form"):
        html(ui.section("Streaming", "pick the best option every week, ranked on THIS week only"))
        c1, c2, c3 = st.columns(3)
        dst = c1.toggle("Stream D/ST", value=cur.stream_dst, help="Re-pick the defense every week on matchup (opponent's implied points, turnovers, sacks, wind).")
        k = c2.toggle("Stream K", value=cur.stream_k, disabled=not slots.get("K"), help="Only matters if your league has a kicker slot." if slots.get("K") else "Your league has no kicker slot.")
        gain = c3.number_input("Swap only if it gains at least (pts)", 0.0, 10.0, float(cur.stream_swap_gain), 0.5,
                               help="If the best streamer isn't this much better, the app says 'keep your current D/ST'.")
        html(ui.section("Roster caps", "extras beyond what you start"))
        c1, c2, c3 = st.columns(3)
        mq = c1.number_input("Max QBs", 1, 4, int(cur.max_qb), help="Adding a QB at the cap requires dropping a QB.")
        mt = c2.number_input("Extra TEs beyond starters", 0, 3, int(cur.max_te_extra))
        md = c3.number_input("Max D/ST", 1, 3, int(cur.max_dst))
        html(ui.section("Protection and thresholds"))
        c1, c2, c3 = st.columns(3)
        days = c1.number_input("Don't churn players added in the last (days)", 0, 21, int(cur.recent_days))
        mw = c2.number_input("Minimum gain this week (pts)", 0.0, 10.0, float(cur.min_gain_week), 0.5)
        mr = c3.number_input("...or minimum rest-of-season gain (pts)", 0.0, 40.0, float(cur.min_gain_ros), 1.0)
        c1, c2, c3 = st.columns(3)
        spec = c1.number_input("Extra gain needed for one-week spikes (pts)", 0.0, 10.0, float(cur.speculative_extra_gain), 0.5,
                               help="When a projection is far above a player's recent level, the move must clear a higher bar and is labelled speculative.")
        po = c2.number_input("Playoff week weight", 1.0, 3.0, float(cur.playoff_weight), 0.1, help="How much more a fantasy-playoff week counts in rest-of-season values.")
        ex = c3.segmented_control("Explanations", ["Short", "Beginner"], default=cur.explanation, help="Beginner defines terms like D/ST, IR and bye. Short never does.")
        if st.form_submit_button("Save strategy", icon=":material/save:"):
            strategy_mod.save(strategy_mod.Strategy(**{**cur.__dict__, "stream_dst": dst, "stream_k": k, "stream_swap_gain": gain, "max_qb": int(mq), "max_te_extra": int(mt),
                                                       "max_dst": int(md), "recent_days": int(days), "min_gain_week": mw, "min_gain_ros": mr, "speculative_extra_gain": spec,
                                                       "playoff_weight": po, "explanation": ex or "Short"}), ctx.cfg.db_path)
            st.toast("Strategy saved. Recommendations now follow it.")
            st.rerun()
    caps = cur.caps(slots)
    html(f'<div class="fh-ctx">{ui.chip("Slots: " + ", ".join(f"{n}x {kk}" for kk, n in slots.items()), "", "grid_view")}'
         f'{ui.chip("Caps: " + ", ".join(f"{kk} {v}" for kk, v in caps.items()), "", "lock")}{ui.chip("Streaming: " + (", ".join(sorted(cur.streaming)) or "none"), "", "autorenew")}</div>')


def render(ctx: Ctx) -> None:
    sel = st.segmented_control("More", ["News", "My strategy", "Edge engine", "Recommendation log"], default="News", key="more_sel", label_visibility="collapsed") or "News"
    {"News": _news, "My strategy": _strategy, "Edge engine": _edge_engine}.get(sel, _log)(ctx)
