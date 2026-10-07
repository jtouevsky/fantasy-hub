"""Modal sheets: player details and contextual AI reviews."""
from __future__ import annotations

import streamlit as st

import ai_runner
import assets
from edge import live as edge_live, usage as edge_usage
import news as news_mod
import ui
import waivers
from ctx import Ctx
from optimizer import availability
from views_common import move_gain


def _team_label(t) -> str:
    return f"{t.owners[0].first_name} · {t.name}" if t.owners and t.owners[0].first_name else t.name


def _ownership_chip(ctx: Ctx, p) -> str:
    owner = ctx.owner_of(p)
    if owner and owner.team_id == ctx.me.team_id:
        return ui.chip("On your team", "good", "shield")
    if owner:
        return ui.chip(f"On {owner.name}", "", "groups")
    own = f" · {p.percent_owned:.0f}% owned" if p.percent_owned >= 0 else ""
    return ui.chip(f"Free agent{own}", "info", "person_add")


def _compare_table(ctx: Ctx, a, b) -> str:
    m = ctx.model
    ctx.brand.prefetch([a, b])
    face = lambda p: f'<div style="display:flex;flex-direction:column;align-items:center;gap:6px">{ctx.brand.avatar(p, 52)}<span>{ui.esc(p.name)}</span></div>'
    rows = [("This week (proj)", a.week_proj, b.week_proj, True), ("Points per game", m.ppg(a), m.ppg(b), True),
            ("Rest-of-season value", m.value(a), m.value(b), True), ("Games left", m.games_left(a), m.games_left(b), True)]
    body = ""
    for label, x, y, hi in rows:
        bx, by = (" best" if x > y else ""), (" best" if y > x else "")
        body += f'<tr><td>{label}</td><td class="{bx.strip()}">{x:.1f}</td><td class="{by.strip()}">{y:.1f}</td></tr>'
    body += f'<tr><td>Status</td><td>{ui.esc(a.injury_status.title().replace("_", " "))}</td><td>{ui.esc(b.injury_status.title().replace("_", " "))}</td></tr>'
    return f'<table class="cmp"><tr><th></th><th style="text-transform:none;letter-spacing:0">{face(a)}</th><th style="text-transform:none;letter-spacing:0">{face(b)}</th></tr>{body}</table>'


@st.dialog("Player", width="large")
def player_sheet(ctx: Ctx, pid: int) -> None:
    p = ctx.everyone().get(pid)
    if p is None:
        st.html(ui.notice("That player isn't in the current data. Try Refresh.", "warn", "person_off"))
        return
    b, m, snap = ctx.brand, ctx.model, ctx.snap
    b.prefetch([p], widths=(360,))
    team = assets.team(p.pro_team, ctx.cfg.db_path)
    tc = b.color(p.pro_team)
    st.html(
        f'<div class="hero-player" style="--tc:{tc}">{b.avatar(p, 120)}<div style="min-width:0"><h2>{ui.esc(p.name)}</h2>'
        f'<div class="fh-ctx" style="margin-top:10px">{ui.chip(p.position, "pos")}{b.status_chip(p)}{_ownership_chip(ctx, p)}'
        f'{ui.chip("Watching", "", "star") if p.player_id in ctx.watchlist else ""}</div>'
        f'<div style="margin-top:10px">{b.team_banner(p.pro_team)}</div></div></div>'
        f'<div class="kv"><div><b>{"-" if p.on_bye else f"{p.week_proj:.1f}"}</b><small>Week {snap.week} {"ESPN " + format(p.espn_week_proj, ".1f") + " → adjusted" if p.has_edge else "projection"}</small></div>'
        f'<div><b>{m.ppg(p):.1f}</b><small>Points / game (blended)</small></div><div><b>{p.total_points:.1f}</b><small>Season points · {p.games_played} G</small></div>'
        f'<div><b>{m.value(p):.0f}</b><small>Rest-of-season value</small></div></div>')

    gsis = (ctx.edge.gsis_of.get(p.player_id) if ctx.edge else None)
    if gsis and not ctx.demo:
        try:
            cells = edge_usage.usage_cells(edge_usage.usage_summary(edge_live.get_hist(snap.year, ctx.cfg.db_path), gsis, snap.year, snap.year * 100 + snap.week), p.position)
        except Exception:
            cells = []
        if cells:
            st.html(ui.section("Usage & opportunity", "this season, from play-by-play data") + '<div class="kv">' +
                    "".join(f'<div><b>{ui.esc(v)}</b><small>{ui.esc(lab)}</small><span class="hint">{ui.esc(hint)}</span></div>' for v, lab, hint in cells) + "</div>")
    if p.context:
        st.html(ui.section("Opportunity context", "information only"))
        st.html(ui.edge_context(p, open_=True))
    if p.has_edge or p.tags:
        st.html(ui.section("Edge vs ESPN", "adjustments on top of ESPN's projection"))
        if p.has_edge:
            st.html(ui.edge_why(p, open_=True))
        elif p.tags:
            st.html(ui.notice("No projection adjustment this week for him (no data, or nothing cleared the noise threshold).", "", "info"))
        for tg, txt in p.tags:
            st.html(f'<div class="notice"><span class="chip tag">{ui.icon(ui.TAG_ICON.get(tg, "sell"))}{ui.esc(tg)}</span><div>{ui.esc(txt)}</div></div>')
        if p.edge_ros:
            st.html(f'<div class="fresh">{ui.icon("calendar_month")}Rest-of-season edge: {p.edge_ros:+.1f} pts/game (feeds trade and waiver value).</div>')
    elif ctx.edge is not None and p.position in ("QB", "RB", "WR", "TE") and not p.on_bye:
        st.html(ui.notice("No edge data for this player this week - ESPN's projection is used as is.", "", "info"))
    if ctx.edge is not None:
        env = ctx.edge.game_env.get(p.pro_team)
        if env:
            st.html(ui.section("Game environment") + ui.game_env_html(env))
    nxt = f"Week {snap.week}: " + (f"vs {p.opponent}, {ui.kick_label(p)}" if p.opponent else ("bye week" if p.on_bye else "no game info")) + (f" · bye is week {p.bye_week}" if p.bye_week else "")
    st.html(ui.section("Fantasy points by game", "your league's scoring"))
    slot = st.empty()
    slot.html(ui.skeleton(1, 190))
    hist = ctx.history(p)
    notes = ", ".join(f"{k.replace('points_per_', '').replace('_', ' ')} {v:g}" for k, v in snap.scoring_notes.items())
    if ctx.demo:
        slot.html(ui.notice("Demo data: this history is made up.", "warn", "science") + ui.trend_chart(hist, color=tc, current_season=snap.year, week_proj=p.week_proj, current_week=snap.week, scoring_note=notes))
    elif hist:
        slot.html(ui.trend_chart(hist, color=tc, current_season=snap.year, week_proj=0 if p.on_bye else p.week_proj, current_week=snap.week, scoring_note=notes))
    else:
        slot.html(ui.notice("Game history couldn't be loaded from ESPN right now.", "warn", "cloud_off"))
    st.html(f'<div class="fresh">{ui.icon("event")}{ui.esc(nxt)}</div>')

    # ---- decision context ----
    owner = ctx.owner_of(p)
    st.html(ui.section("What you could do"))
    if owner and owner.team_id == ctx.me.team_id:
        plan = ctx.plan()
        occupied = [(s, q) for s, q in plan.current if q and q.player_id != p.player_id and s in p.eligible_slots]
        starting = p.lineup_slot not in ("BE", "IR")
        if p.lineup_slot == "IR":
            st.html(ui.notice("On injured reserve; he can't be started until he returns.", "", "personal_injury"))
        elif occupied:
            rows = "".join(f'<tr><td>{ui.esc(s)}: {ui.esc(q.name)}</td><td>{availability(q):.1f}</td><td>{availability(p):.1f}</td>'
                           f'<td class="{"best" if availability(p) > availability(q) else ""}">{availability(p) - availability(q):+.1f}</td></tr>' for s, q in occupied)
            st.html(f'<table class="cmp"><tr><th>Slot / current starter</th><th>Theirs</th><th>{ui.esc(p.name.split()[-1])}</th><th>Change</th></tr>{rows}</table>'
                    f'<div class="fresh" style="margin-top:6px">Risk-adjusted projections for this week. Make changes in the ESPN app.</div>')
        elif starting:
            st.html(ui.notice("He's in your starting lineup.", "good", "check_circle"))
    elif owner is None:
        sugg = waivers.suggest_add_drops(snap, m, [p], ctx.index, ctx.trending, 1) if ctx.fas else []
        if sugg:
            s = sugg[0]
            st.html(b.rec_card(f"Add {p.name}, drop {s.drop.name}", ui.esc(s.reason), ic="person_add", gain=move_gain(s)[0], gain_label=move_gain(s)[1], todo=s.action()))
        else:
            st.html(ui.notice("Adding him wouldn't clearly improve your lineup this week or for the rest of the season.", "", "info"))
    else:
        st.html(ui.notice(f"He's on {ui.esc(owner.name)} ({ui.esc(owner.owner_label)}). A trade is the way to get him.", "", "swap_horiz"))
        if st.button(f"Explore a trade with {owner.owner_label.split()[0] if owner.owner_label else owner.name}", icon=":material/swap_horiz:", key="sheet_trade"):
            Ctx.goto("Trades", trade_partner=_team_label(owner))
            st.rerun()

    # ---- news ----
    st.html(ui.section("Latest news"))
    for ev in [e for e in ctx.events if e.get("player_espn_id") == pid][:2]:
        st.html(ui.news_event_html(ev))
    fetch = ctx.news_fetch()
    if fetch is None:
        st.html(ui.notice("News isn't available in demo mode.", "", "newspaper"))
    else:
        try:
            pn = news_mod.get_player_news(p, fetch, ctx.index, db_path=ctx.cfg.db_path)
            if pn.injury_line:
                st.html(ui.notice(f"<b>Sleeper injury:</b> {ui.esc(pn.injury_line)}" + (f" - {ui.esc(pn.sleeper.get('injury_notes', ''))}" if pn.sleeper.get("injury_notes") else ""), "warn", "medical_services"))
            if not pn.items:
                st.html(ui.notice("No recent news from ESPN.", "", "newspaper"))
            for it in pn.items[:3]:
                st.html(f'<div class="news"><b>{ui.esc(it.headline)}</b><p>{ui.esc(it.story[:420])}{"..." if len(it.story) > 420 else ""}</p>'
                        f'<small>{ui.esc(it.source)} · {ui.esc(it.published[:10])} · reported news, not AI</small></div>')
        except Exception:
            st.html(ui.notice("News couldn't be loaded. The rest of this sheet is unaffected.", "warn", "cloud_off"))

    # ---- compare + AI ----
    st.html(ui.section("Compare"))
    others = {q.name + f" · {q.position} · {q.pro_team}": q for q in ctx.everyone().values() if q.position == p.position and q.player_id != p.player_id}
    pick = st.selectbox("Compare with", list(others), index=None, key=f"cmp_{pid}", placeholder=f"Another {p.position}", label_visibility="collapsed")
    if pick:
        st.html(_compare_table(ctx, p, others[pick]))
    c1, c2, c3 = st.columns([1.5, 1.7, 1.6])
    watching = p.player_id in ctx.watchlist
    if c3.button("Remove from watchlist" if watching else "Add to watchlist", key="sheet_watch", icon=":material/star:" if watching else ":material/star_border:"):
        from ctx import toggle_watch
        toggle_watch(p.player_id, ctx.cfg.db_path)
        st.rerun()
    if c1.button("Explain projection", key="sheet_explain", icon=":material/auto_awesome:"):
        Ctx.ask_ai(f"Explain {p.name}'s week {snap.week} projection and what I should do with him. Use get_player_news and my roster.", f"{p.name}: projection")
        st.rerun()
    if pick and c2.button("Ask AI to compare", key="sheet_cmp_ai", icon=":material/balance:"):
        Ctx.ask_ai(f"Compare {p.name} and {others[pick].name} for my team this week. Who should I prefer and why?", "Player comparison")
        st.rerun()


@st.dialog("AI review", width="large")
def ai_sheet(ctx: Ctx, req: dict) -> None:
    st.html(f'<div class="fh-ctx"><span class="chip ai">{ui.icon("auto_awesome")}AI advice</span>'
            + "".join(ui.chip(t, "", i) for t, i in ai_runner.context_chips(ctx)) + "</div>"
            f'<div class="fresh" style="margin:8px 0 12px">Context is read from your league automatically. Wrong team or week? Refresh first.</div>')
    st.markdown(f"**{req['title']}**")
    cache = st.session_state.setdefault("_ai_cache", {})
    key = (req["prompt"], ctx.snap.fetched_at)
    slot = st.empty()
    if key not in cache:
        slot.html(ui.skeleton(3, 46) + '<div class="fresh">Reviewing your league data...</div>')
        try:
            res = ai_runner.run(ctx, req["prompt"])
            cache[key] = {"text": res.text, "trace": res.tool_trace, "at": ai_runner.stamp()}
        except ai_runner.AIUnavailable as e:
            slot.html(ui.notice(ui.esc(str(e)), "warn", "smart_toy"))
            return
        except Exception as e:
            slot.html(ui.notice(f"The AI request failed ({ui.esc(type(e).__name__)}). Your team data is fine; you can try again.", "bad", "error"))
            if st.button("Try again", key="ai_retry", icon=":material/refresh:"):
                st.rerun(scope="fragment")
            return
    out = cache[key]
    slot.empty()
    with st.container(key="ai_answer"):
        st.markdown(out["text"])
    st.html(f'<div class="fresh">{ui.icon("schedule")}AI wrote this at {out["at"]} using data from {ui.ago(ctx.age)}. Treat it as advice; numbers come from ESPN data and the value model.</div>')
    with st.expander(f"What the AI looked up ({len(out['trace'])})"):
        for t in out["trace"]:
            st.html(f'<div class="tool">{ui.icon("data_object")} {ui.esc(t["tool"])}({ui.esc(str(t["input"])[:140])}){" - failed" if t["error"] else ""}</div>')
    st.caption("Nothing was changed in ESPN. Make any move yourself in the ESPN app.")
