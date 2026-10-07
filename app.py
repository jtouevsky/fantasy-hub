"""Fantasy Hub - Streamlit UI. Run with:  streamlit run app.py

Read-only: every recommendation ends with something to do manually in the ESPN app."""
from __future__ import annotations

import os
import time

import pandas as pd
import streamlit as st

import db
import demo_data
from config import load_config
from league_client import LeagueClient, LeagueConnectionError, get_free_agents, get_snapshot
from models import LeagueSnapshot, PlayerInfo
from optimizer import availability, plan_lineup
from valuation import ValueModel
import sleeper
import waivers

st.set_page_config(page_title="Fantasy Hub", page_icon="🏈", layout="wide")

SLOT_ORDER = ["QB", "RB", "WR", "TE", "RB/WR", "WR/TE", "FLEX", "OP", "D/ST", "K", "BE", "IR"]


# ---------------------------------------------------------------------------
# Data access (live ESPN, or demo data when no credentials are configured)
# ---------------------------------------------------------------------------
@st.cache_resource
def _client() -> LeagueClient:
    return LeagueClient(load_config())


def using_demo() -> bool:
    return bool(st.session_state.get("demo")) or os.getenv("DEMO_MODE") == "1"


def load_snapshot(force: bool = False) -> LeagueSnapshot:
    if using_demo():
        return demo_data.build_demo_snapshot()
    return get_snapshot(_client(), force=force)


def load_free_agents(position: str | None = None, size: int = 50, force: bool = False) -> list[PlayerInfo]:
    if using_demo():
        fas = demo_data.build_demo_free_agents()
        return [p for p in fas if position in (None, p.position)]
    return get_free_agents(_client(), position, size, force=force)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def _slot_key(p: PlayerInfo) -> tuple[int, float]:
    s = p.lineup_slot
    return (SLOT_ORDER.index(s) if s in SLOT_ORDER else 99, -p.week_proj)


def _status_label(p: PlayerInfo) -> str:
    if p.on_bye:
        return "BYE"
    return "" if p.injury_status == "ACTIVE" else p.injury_status.replace("_", " ")


def roster_frame(players: list[PlayerInfo]) -> pd.DataFrame:
    rows = []
    for p in sorted(players, key=_slot_key):
        rows.append({
            "Slot": p.lineup_slot, "Player": p.name, "Pos": p.position, "NFL": p.pro_team,
            "Opp": p.opponent or ("BYE" if p.on_bye else ""), "Status": _status_label(p),
            "Proj (wk)": round(p.week_proj, 1), "Actual (wk)": round(p.week_points, 1),
            "Season pts": round(p.total_points, 1), "PPG": round(p.actual_ppg, 1),
            "Proj PPG": round(p.season_proj_ppg, 1),
        })
    return pd.DataFrame(rows)


def render_dashboard(snap: LeagueSnapshot) -> None:
    me = snap.my_team
    m = snap.matchup_for(me.team_id)
    st.subheader(f"{me.name}  ·  {me.record}  ·  #{me.standing} in standings")

    st.markdown(f"#### Week {snap.week} matchup")
    opp = snap.team(m.opponent_of(me.team_id)) if m else None
    if m and opp:
        mine_home = m.home_team_id == me.team_id
        my_score, op_score = (m.home_score, m.away_score) if mine_home else (m.away_score, m.home_score)
        my_proj, op_proj = (m.home_proj, m.away_proj) if mine_home else (m.away_proj, m.home_proj)
        c1, c2, c3 = st.columns(3)
        c1.metric(me.name, f"{my_proj:.1f} proj", f"{my_score:.1f} so far", delta_color="off")
        c2.metric(f"vs {opp.name}", f"{op_proj:.1f} proj", f"{op_score:.1f} so far", delta_color="off")
        edge = my_proj - op_proj
        c3.metric("Projected edge", f"{edge:+.1f} pts", "favored" if edge > 0 else "underdog", delta_color="normal" if edge > 0 else "inverse")
        st.caption(f"Opponent: {opp.owner_label or opp.name}")
    else:
        st.info("No matchup found for this week (bye week or season not started).")

    st.markdown("#### My roster")
    st.dataframe(roster_frame(me.roster), hide_index=True, width="stretch")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### Standings")
        rows = [{
            "#": t.standing, "Team": t.name, "Owner": t.owner_label, "Record": t.record,
            "PF": round(t.points_for, 1), "PA": round(t.points_against, 1),
            "Playoff %": round(t.playoff_pct, 0) if t.playoff_pct else None,
        } for t in snap.standings()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    with right:
        st.markdown("#### Injury & bye report (my roster)")
        flagged = [p for p in me.roster if p.injury_status != "ACTIVE" or p.on_bye]
        if not flagged:
            st.success("Nobody on your roster is injured or on a bye.")
        for p in sorted(flagged, key=_slot_key):
            starting = p.lineup_slot not in ("BE", "IR")
            tag = "⚠️ STARTING" if starting else "bench"
            st.markdown(f"- **{p.name}** ({p.position}, {p.pro_team}) — {_status_label(p)} · {tag}")


# ---------------------------------------------------------------------------
# Lineup optimizer
# ---------------------------------------------------------------------------
def _lineup_frame(rows) -> pd.DataFrame:
    return pd.DataFrame([{
        "Slot": slot, "Player": p.name if p else "(empty)", "Pos": p.position if p else "",
        "Status": _status_label(p) if p else "", "Proj": round(p.week_proj, 1) if p else 0.0,
        "Risk-adj": round(availability(p), 1) if p else 0.0,
    } for slot, p in rows])


def render_lineup(snap: LeagueSnapshot) -> None:
    plan = plan_lineup(snap.my_team.roster, snap.starter_slots)
    c1, c2, c3 = st.columns(3)
    c1.metric("Current lineup", f"{plan.current_total:.1f}")
    c2.metric("Optimal lineup", f"{plan.optimal_total:.1f}")
    c3.metric("Gain", f"{plan.gain:+.1f} pts")
    st.caption("Risk-adjusted: Questionable x0.92, Doubtful x0.5; Out/bye/IR players are never started.")
    if not plan.swaps:
        st.success("Your lineup is already optimal. No changes needed.")
    for s in plan.swaps:
        st.info(f"**{s.gain:+.1f} pts** - {s.action()}  \n{s.reason}")
    for w in plan.warnings:
        st.warning(w)
    a, b = st.columns(2)
    a.markdown("#### Current"); a.dataframe(_lineup_frame(plan.current), hide_index=True, width="stretch")
    b.markdown("#### Optimal"); b.dataframe(_lineup_frame(plan.optimal), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# Shared analysis context (value model, free agents, Sleeper)
# ---------------------------------------------------------------------------
FA_POSITIONS = ["QB", "RB", "WR", "TE", "K", "D/ST"]


def load_context(snap: LeagueSnapshot):
    """Free agents for every position the league starts, a ValueModel, and Sleeper trending (best effort)."""
    flexy = {"FLEX", "OP", "RB/WR", "WR/TE"} & set(snap.starter_slots)
    positions = [pos for pos in FA_POSITIONS
                 if pos in snap.starter_slots or (pos in ("RB", "WR", "TE") and flexy) or (pos == "QB" and "OP" in flexy)]
    fas = [p for pos in positions for p in load_free_agents(pos, 30)]
    model = ValueModel(snap, fas)
    index, trending = None, {}
    if not using_demo():
        try:
            index = sleeper.SleeperIndex(sleeper.load_players(load_config().db_path))
            trending = sleeper.trending_counts(index, "add", load_config().db_path)
        except Exception as e:  # Sleeper is a nice-to-have
            st.sidebar.caption(f"Sleeper unavailable: {type(e).__name__}")
    return fas, model, index, trending


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------
def render_waivers(snap: LeagueSnapshot, fas, model, index, trending) -> None:
    st.markdown("#### Suggested add / drop moves")
    sugg = waivers.suggest_add_drops(snap, model, fas, index, trending)
    if not sugg:
        st.success("No add/drop is worth making right now.")
    for r in sugg:
        fire = " 🔥 trending" if r.trending_adds else ""
        st.info(f"**Add {r.add.name}** ({r.add.position}, {r.add.pro_team}){fire}  ->  drop **{r.drop.name}**  \n"
                f"**{r.ppg_gain:+.1f} pts/week** rest of season · {r.weekly_gain:+.1f} this week  \n"
                f"{r.reason}  \n_{r.action()}_")

    ranks = waivers.rank_free_agents(model, fas, index, trending)
    pos_filter = st.selectbox("Position", ["All"] + sorted({r.player.position for r in ranks}), key="fa_pos")
    ranks = [r for r in ranks if pos_filter in ("All", r.player.position)]

    def table(rows):
        return pd.DataFrame([{
            "Player": r.player.name, "Pos": r.player.position, "NFL": r.player.pro_team,
            "Status": _status_label(r.player), "ROS value": round(r.ros_value, 1), "This wk": round(r.week_value, 1),
            "Owned %": r.player.percent_owned, "Trending adds (24h)": r.trending_adds or None,
            "Breakout": "🔥" if r.breakout else "",
        } for r in rows])

    a, b = st.columns(2)
    a.markdown("#### Best rest-of-season value")
    a.dataframe(table(sorted(ranks, key=lambda r: -r.ros_value)[:20]), hide_index=True, width="stretch")
    b.markdown("#### Best this week")
    b.dataframe(table(sorted(ranks, key=lambda r: -r.week_value)[:20]), hide_index=True, width="stretch")
    st.caption("ROS value = points over a replacement-level player across the remaining games (see README). "
               "Breakout = trending on Sleeper and under 50% owned.")


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------
def render_setup_help(err: str | None = None) -> None:
    st.title("🏈 Fantasy Hub")
    st.warning(err or "ESPN credentials aren't configured yet.")
    st.markdown(
        "1. Copy `.env.example` to `.env`\n"
        "2. Fill in `LEAGUE_ID`, `TEAM_ID`, `ESPN_S2`, `SWID` (see the README for exactly where to find them)\n"
        "3. Restart the app.\n\n"
        "Want to look around first? Use the demo league (fake data)."
    )
    if st.button("Use demo data"):
        st.session_state["demo"] = True
        st.rerun()


def main() -> None:
    cfg = load_config()
    demo = using_demo()

    with st.sidebar:
        st.title("🏈 Fantasy Hub")
        if demo:
            st.warning("DEMO MODE - fake data")
            if st.button("Exit demo"):
                st.session_state["demo"] = False
                st.rerun()
        force = st.button("↻ Refresh from ESPN", disabled=demo)
        if not demo:
            age = db.cache_age(f"snapshot:{cfg.league_id}:{cfg.year}", cfg.db_path)
            st.caption(f"Cache TTL {cfg.cache_ttl}s" + (f" · data is {int(age)}s old" if age is not None else ""))
        st.caption("Read-only. Make moves yourself in the ESPN app.")

    if not demo and cfg.missing_espn():
        render_setup_help()
        return
    try:
        snap = load_snapshot(force=force)
    except LeagueConnectionError as e:
        render_setup_help(str(e))
        return

    if not demo and _client().last_warning:
        st.warning(_client().last_warning)
    st.title(snap.league_name)
    st.caption(f"{snap.year} season · Week {snap.week} · {snap.team_count} teams · starters: "
               + ", ".join(f"{n}× {s}" for s, n in snap.starter_slots.items())
               + f" · {snap.bench_slots} bench")

    fas, model, index, trending = load_context(snap)
    tab_dash, tab_lineup, tab_waiver = st.tabs(["Dashboard", "Lineup", "Waivers"])
    with tab_dash:
        render_dashboard(snap)
    with tab_lineup:
        render_lineup(snap)
    with tab_waiver:
        render_waivers(snap, fas, model, index, trending)


main()
