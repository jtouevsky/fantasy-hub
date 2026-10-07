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


_CONF = {"high": ("good", "verified"), "medium": ("", "help"), "low": ("warn", "warning")}


def move_card(ctx: Ctx, m, key: str, ask: bool = True) -> None:
    """Compact add/drop card: headline gain, one line, confidence; the full reason sits in an expander."""
    b = ctx.brand
    title = f"Add {m.add.name}" + (f", drop {m.drop.name}" if m.drop else "")
    first = m.reason.split("; ")[0].rstrip(".") + "."
    kind, ic = _CONF[m.confidence]
    chips = f'{ui.chip(m.confidence.title() + " confidence", kind, ic)}' + (f'{ui.chip("Speculative", "warn", "bolt")}' if "speculative" in m.flags else "") \
        + (f'{ui.chip("Streamer", "", "autorenew")}' if "streamer" in m.flags else "")
    html(b.rec_card(title, ui.esc(first), ic="person_add", gain=m.gain_week, gain_label="this week",
                    why=f"{m.add.position} · {m.add.pro_team} · rest of season {m.gain_ros:+.1f} pts", players=[m.add] + ([m.drop] if m.drop else [])))
    html(f'<div class="fh-ctx" style="margin:-6px 0 6px">{chips}</div>')
    with st.expander("Why", icon=":material/info:"):
        st.write(m.reason)
        st.caption(m.action())
        if ask:
            ai_button("Ask AI about this", f"mv_{key}", f"Check this move with evaluate_move: add {m.add.name}" + (f", drop {m.drop.name}" if m.drop else "") + ".", "Waiver move review")


def stream_card(ctx: Ctx, sp, key: str) -> None:
    """Streaming decision for D/ST or K: swap only if the gain clears the threshold, otherwise say keep."""
    cur = sp.current.name if sp.current else "nobody"
    if sp.swap and sp.best:
        html(ctx.brand.rec_card(f"Stream {sp.position}: add {sp.best.name}" + (f", drop {cur}" if sp.current else ""), ui.esc(sp.reason), ic="autorenew",
                                gain=sp.gain, gain_label="this week", why=sp.plan_ahead, players=[sp.best]))
    else:
        html(ui.notice(f"<b>{ui.esc(sp.reason)}</b>" + (f" {ui.esc(sp.plan_ahead)}" if sp.plan_ahead else ""), "good", "check_circle"))


def moves_block(ctx: Ctx, key: str, max_moves: int = 3, show_streams: bool = True, limit_cards: int = 99, show_empty: bool = True) -> int:
    """Render the shared move engine's answer. Returns how many cards were shown (0 = 'no move needed')."""
    ms = ctx.hub.moves.find_moves(max_moves)
    n = 0
    if show_streams:
        for i, sp in enumerate(ms.streams):
            stream_card(ctx, sp, f"{key}s{i}")
            n += int(sp.swap)
    for i, m in enumerate(ms.moves[:limit_cards]):
        move_card(ctx, m, f"{key}{i}")
        n += 1
    if ms.empty and show_empty:
        html(ui.notice(f"<b>No move needed.</b> {ui.esc(ms.no_move_reason)}", "good", "check_circle"))
    return n


def moves_from_trace(trace: list[dict], key: str) -> None:
    """Assistant answers that used find_moves also show the engine's moves as compact cards (the answer text can only repeat these)."""
    for t in trace:
        if t["tool"] != "find_moves" or t["error"]:
            continue
        res = t["result"]
        for i, m in enumerate(res.get("moves", [])):
            kind, ic = _CONF[m["confidence"]]
            title = f"Add {m['add']}" + (f", drop {m['drop']}" if m["drop"] else "")
            chips = ui.chip(m["confidence"].title() + " confidence", kind, ic) + (ui.chip("Speculative", "warn", "bolt") if "speculative" in m["flags"] else "")
            html(f'<div class="mv glass-med"><div class="mvh"><b>{ui.esc(title)}</b><span class="num">{m["gain_this_week"]:+.1f} this week · {m["gain_rest_of_season"]:+.1f} rest of season</span></div>'
                 f'<div class="fh-ctx">{chips}</div></div>')
            with st.expander("Why", icon=":material/info:"):
                st.write(m["reason"])
        for sp in res.get("streaming", []):
            line = (f"Stream {sp['position']}: add {sp['best']}" + (f", drop {sp['current']}" if sp["current"] else "")) if sp["swap"] else f"Keep your current {sp['position']} ({sp['current']})"
            html(ui.notice(f"<b>{ui.esc(line)}</b>. {ui.esc(sp['reason'])}", "" if sp["swap"] else "good", "autorenew" if sp["swap"] else "check_circle"))
        if res.get("no_move_needed"):
            html(ui.notice("<b>No move needed.</b> " + ui.esc(res.get("no_move_reason", "")), "good", "check_circle"))
