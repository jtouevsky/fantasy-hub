"""Helpers shared by the page modules."""
from __future__ import annotations

from typing import Iterable

import streamlit as st

import ui
from ctx import Ctx
from models import PlayerInfo


def html(s: str) -> None:
    st.html(s)


def player_list(ctx: Ctx, key: str, items: Iterable[tuple[PlayerInfo, dict]], empty_title: str = "No players match these filters",
                empty_body: str = "Try clearing a filter.") -> None:
    """Rows with a round 'open details' button beside each one."""
    items = list(items)
    if not items:
        html(ui.empty(empty_title, empty_body))
        return
    ctx.brand.prefetch([p for p, _ in items])
    with st.container(key=f"lst_{key}"):
        for p, kw in items:
            c1, c2 = st.columns([30, 2], vertical_alignment="center", gap="small")
            c1.html(ctx.brand.player_row(p, **kw))
            c2.button(f"Details for {p.name}", key=f"open_{key}_{p.player_id}", icon=":material/chevron_right:",
                      on_click=Ctx.open_player, args=(p.player_id,), help=f"Open {p.name}")


def ai_button(label: str, key: str, prompt: str, title: str, ic: str = "auto_awesome") -> None:
    st.button(label, key=f"ai_{key}", icon=f":material/{ic}:", on_click=Ctx.ask_ai, args=(prompt, title),
              help="Opens an AI review. It only reads your league and never makes changes.")


def goto_button(label: str, key: str, page: str, ic: str = "arrow_forward", **state) -> None:
    st.button(label, key=f"go_{key}", icon=f":material/{ic}:", on_click=Ctx.goto, args=(page,), kwargs=state)


def matchup_state(ctx: Ctx) -> str:
    """Pregame / In progress / Games complete, from real kickoff times of both starting lineups."""
    from datetime import datetime, timedelta
    opp = ctx.opp
    starters = [p for t in (ctx.me, opp) if t for p in t.roster if p.lineup_slot not in ("BE", "IR") and ui.kickoff(p)]
    if not starters:
        return "Pregame"
    now = datetime.now()
    started = [ui.kickoff(p) <= now for p in starters]
    if not any(started):
        return "Pregame"
    if all(ui.kickoff(p) + timedelta(hours=4) <= now for p in starters):
        return "Games complete"
    return "In progress"


def move_gain(s) -> tuple[float, str]:
    """Headline number for an add/drop: weekly rest-of-season gain, or this-week gain for pure streaming moves."""
    if abs(s.ppg_gain) >= 0.5 or abs(s.weekly_gain) < 0.5:
        return s.ppg_gain, "pts / week"
    return s.weekly_gain, "this week only"
