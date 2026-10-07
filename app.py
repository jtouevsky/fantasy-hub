"""Fantasy Hub - Streamlit UI.  Run with:  streamlit run app.py

Read-only: every recommendation ends with something to do manually in the ESPN app.
This file is the shell (theme, header, search, navigation, dialogs); each page lives in view_*.py.
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Fantasy Hub", page_icon=":material/sports_football:", layout="wide", initial_sidebar_state="collapsed")

import assets  # noqa: E402
import dialogs  # noqa: E402
import theme  # noqa: E402
import ui  # noqa: E402
import view_assistant, view_league, view_matchup, view_more, view_overview, view_players, view_team, view_trades  # noqa: E402,E401
from config import load_config  # noqa: E402
from ctx import Ctx, load_ctx, using_demo  # noqa: E402
from league_client import LeagueConnectionError  # noqa: E402

PAGES = [("Overview", "home", view_overview), ("My Team", "sports_football", view_team), ("Matchup", "scoreboard", view_matchup),
         ("Players", "person_search", view_players), ("Trades", "swap_horiz", view_trades), ("League", "leaderboard", view_league),
         ("Assistant", "auto_awesome", view_assistant), ("More", "more_horiz", view_more)]
LABELS = {f":material/{ic}: {name}": (name, mod) for name, ic, mod in PAGES}


def apply_theme(cfg) -> None:
    mode = theme.get_mode(cfg.db_path)
    accent, ink = "#4f74e3", "#ffffff"
    fav = theme.get_accent_team(cfg.db_path)
    if fav:
        t = assets.team(fav, cfg.db_path)
        if t.abbr != "NFL":
            accent = assets.usable_color(t.color)
            ink = assets.on_color(accent)
    st.html(theme.css(mode, accent, ink))
    st.html(theme.SHORTCUT_JS, unsafe_allow_javascript=True)


def setup_screen(cfg, problem: str | None = None) -> None:
    st.html('<div class="fh-top"><div class="fh-brand"><div class="fh-mark"><span class="ms">sports_football</span></div><div><b>Fantasy Hub</b><small>Your weekly team manager</small></div></div></div>')
    st.html(ui.empty("Connect your league" if not problem else "Couldn't reach your league",
                     problem or "Add LEAGUE_ID, TEAM_ID, ESPN_S2 and SWID to the .env file (see the README), then restart.", "link_off"))
    if st.button("Explore with demo data", icon=":material/science:", type="primary"):
        st.session_state["demo"] = True
        st.rerun()
    if problem:
        st.button("Try again", icon=":material/refresh:", on_click=lambda: st.cache_resource.clear())


def header(ctx: Ctx, cfg) -> bool:
    """Brand, league context, search, refresh, appearance. Returns True if Refresh was pressed."""
    snap = ctx.snap
    ctx.brand.prefetch([], [ctx.me])
    top = st.container(key="topbar")
    c1, c2, c3, c4 = top.columns([6, 4, 1.6, 0.9], vertical_alignment="center", gap="small")
    demo_chip = ui.chip("Demo data", "warn", "science") if ctx.demo else ""
    c1.html(f'<div class="fh-top" style="padding:0"><div class="fh-brand"><div class="fh-mark"><span class="ms">sports_football</span></div>'
            f'<div><b>Fantasy Hub</b><small>{ui.esc(snap.league_name)} · {snap.year}</small></div></div></div>'
            f'<div class="fh-ctx" style="margin-top:8px">{ui.chip(f"Week {snap.week}", "info", "calendar_month")}'
            f'<span class="chip plain" style="padding-left:4px">{ctx.brand.team_avatar(ctx.me, 22)}&nbsp;{ui.esc(ctx.me.name)}</span>{ui.chip(ctx.me.record, "", "sports_score")}{demo_chip}'
            f'{"" if ctx.demo else ui.fresh(ctx.age, cfg.cache_ttl)}</div>')
    everyone = sorted(ctx.everyone().values(), key=lambda p: p.name)
    labels = {f"{p.name} · {p.position} · {p.pro_team}": p.player_id for p in everyone}

    def on_search():
        sel = st.session_state.get("search")
        if sel in labels:
            st.session_state["open_player"] = labels[sel]
        st.session_state["search"] = None

    with c2:
        st.selectbox("Search players", list(labels), index=None, key="search", placeholder="Search players   ( / )", label_visibility="collapsed", on_change=on_search)
    refresh = c3.button("Refresh", icon=":material/refresh:", key="refresh", disabled=ctx.demo, help="Demo data never changes." if ctx.demo else "Fetch the latest from ESPN")
    with c4.popover("", icon=":material/tune:", help="Appearance"):
        mode = st.segmented_control("Theme", theme.MODES, default=theme.get_mode(cfg.db_path), key="theme_sel",
                                    help="System follows your device. Your choice is remembered.")
        if mode and mode != theme.get_mode(cfg.db_path):
            theme.set_mode(mode, cfg.db_path)
            st.rerun()
        teams = assets.nfl_teams(cfg.db_path)
        opts = ["None"] + sorted(t.name for t in teams.values())
        cur = theme.get_accent_team(cfg.db_path)
        cur_name = teams[cur].name if cur in teams else "None"
        pick = st.selectbox("Accent team", opts, index=opts.index(cur_name), key="accent_sel", help="Tints selected states and highlights with a favorite NFL team's color.")
        new = next((a for a, t in teams.items() if t.name == pick), "")
        if new != cur:
            theme.set_accent_team(new, cfg.db_path)
            st.rerun()
    return refresh


def navigation() -> tuple[str, object]:
    if "page_req" in st.session_state:                       # set by buttons elsewhere ("Open My Team", ...)
        want = st.session_state.pop("page_req")
        st.session_state["nav"] = next(k for k, (n, _) in LABELS.items() if n == want)
    st.session_state.setdefault("nav", next(iter(LABELS)))
    with st.container(key="navbar"):
        sel = st.segmented_control("Navigate", list(LABELS), key="nav", label_visibility="collapsed")
    if sel is None:                                          # re-clicking the active item deselects; keep the last page
        sel = st.session_state.get("_last_nav", next(iter(LABELS)))
        st.session_state["nav"] = sel
    st.session_state["_last_nav"] = sel
    return LABELS[sel]


def main() -> None:
    cfg = load_config()
    apply_theme(cfg)
    demo = using_demo()
    if not demo and cfg.missing_espn():
        setup_screen(cfg)
        return
    try:
        force = bool(st.session_state.pop("_force_refresh", False))
        ctx = load_ctx(force=force)
    except LeagueConnectionError as e:
        setup_screen(cfg, str(e))
        return
    except Exception as e:
        setup_screen(cfg, f"Something went wrong loading your league ({type(e).__name__}). Your cached data, if any, is untouched.")
        return

    if header(ctx, cfg):
        st.session_state["_force_refresh"] = True
        st.rerun()
    for w in ctx.warnings:
        st.html(ui.notice(ui.esc(w), "warn", "warning"))
    name, module = navigation()

    try:
        module.render(ctx)
    except Exception as e:                                   # one failed page must not take down the app
        st.html(ui.notice(f"<b>This page hit a problem</b> ({ui.esc(type(e).__name__)}: {ui.esc(str(e)[:160])}). The rest of the app still works.", "bad", "error"))
        st.button("Retry", key="page_retry", icon=":material/refresh:")

    if ctx.demo:
        st.button("Exit demo", key="exit_demo", icon=":material/logout:", on_click=lambda: st.session_state.update(demo=False))

    # dialogs open last so they sit above whichever page rendered
    if "ai_sheet" in st.session_state:
        dialogs.ai_sheet(ctx, st.session_state.pop("ai_sheet"))
    elif "open_player" in st.session_state:
        dialogs.player_sheet(ctx, st.session_state.pop("open_player"))


main()
