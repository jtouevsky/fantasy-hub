"""Matchup: scoreboard with side-by-side starters."""
from __future__ import annotations

import streamlit as st

import ui
from ctx import Ctx
from optimizer import current_lineup
from views_common import ai_button, html, matchup_state


def _half(b, p, right: bool, win: bool, started: bool) -> str:
    if p is None:
        return f'<div class="half{" r" if right else ""}"><span class="fresh">Empty slot</span></div>'
    big = started and p.week_points >= 20
    return (f'<div class="half{" r" if right else ""}{" win" if win else ""}" style="--tc:{b.color(p.pro_team)}">{b.avatar(p, 42)}'
            f'<div style="min-width:0"><div class="nm">{ui.esc(p.name)}</div><div class="sub" style="display:flex;gap:6px;flex-wrap:wrap;margin-top:4px">'
            f'{ui.chip(p.position, "pos")}{b.status_chip(p)}{ui.chip("Big game", "good", "star") if big else ""}'
            f'<span class="fresh">{ui.esc(("vs " + p.opponent) if p.opponent else "Bye")} {ui.esc(ui.kick_label(p) if not p.on_bye else "")}</span></div></div>'
            f'<div class="stat"><b>{p.week_proj:.1f}</b><small class="fresh">{"ESPN " + format(p.espn_week_proj, ".1f") if p.has_edge else "proj"}</small>'
            + (f'<div class="fresh num">actual {p.week_points:.1f}</div>' if started else "") + '</div></div>')


def render(ctx: Ctx) -> None:
    snap, me, opp, b = ctx.snap, ctx.me, ctx.opp, ctx.brand
    m = snap.matchup_for(me.team_id)
    if not (m and opp):
        html(ui.empty("No matchup this week", "Your team has a bye or the schedule hasn't loaded.", "event_busy"))
        return
    state = matchup_state(ctx)
    started = state != "Pregame"
    home = m.home_team_id == me.team_id
    mine, theirs = (m.home_score, m.away_score) if home else (m.away_score, m.home_score)
    mproj, tproj = (m.home_proj, m.away_proj) if home else (m.away_proj, m.home_proj)
    b.prefetch([], [me, opp])
    html(b.scoreboard(me, opp, mine, theirs, mproj, tproj, snap.week, state, ui.fresh(ctx.age, ctx.cfg.cache_ttl)))
    if started and not ctx.demo:
        html(ui.notice("Scores update when you press <b>Refresh</b> (about every few minutes at most). This is not a live feed.", "", "sync"))

    a_rows, b_rows = current_lineup(me.roster, snap.starter_slots), current_lineup(opp.roster, snap.starter_slots)
    remaining = lambda rows: sum(1 for _, p in rows if p and ui.lock_state(p) == "open")
    html(f'<div class="fh-ctx" style="margin-top:14px">{ui.chip(f"{remaining(a_rows)} of your starters yet to play", "", "sports_football")}'
         f'{ui.chip(f"{remaining(b_rows)} of theirs yet to play", "", "sports_football")}</div>')
    ctx.brand.prefetch([p for _, p in a_rows + b_rows if p])

    if ctx.edge and ctx.edge.game_env:
        html(ui.section("Game environment", "Vegas lines + forecast, as of the last refresh"))
        teams = [t for t in {p.pro_team for _, p in a_rows + b_rows if p and p.position != "D/ST"}]
        seen = set()
        for tm in sorted(teams):
            env = ctx.edge.game_env.get(tm)
            if env and frozenset((env.team, env.opp)) not in seen:
                seen.add(frozenset((env.team, env.opp)))
                html(f'<div style="margin:6px 0">{b.team_badge(env.team, 26)} <b>{ui.esc(env.team)}</b> vs {b.team_badge(env.opp, 26)} <b>{ui.esc(env.opp)}</b> <span class="fresh">{ui.esc(env.kickoff)}</span>{ui.game_env_html(env)}</div>')
    html(ui.section("Starters head to head", "your side left"))
    duels = []
    for (slot, pa), (_, pb) in zip(a_rows, b_rows):
        wa = bool(pa and pb and ((pa.week_points > pb.week_points) if started else (pa.week_proj > pb.week_proj)))
        wb = bool(pa and pb and ((pb.week_points > pa.week_points) if started else (pb.week_proj > pa.week_proj)))
        duels.append(f'<div class="duel">{_half(b, pa, False, wa, started)}<div class="mid">{ui.esc(slot)}</div>{_half(b, pb, True, wb, started)}</div>')
    html(f'<div class="solid rows">{"".join(duels)}</div>')
    ta = sum(p.week_proj for _, p in a_rows if p); tb = sum(p.week_proj for _, p in b_rows if p)
    html(f'<div class="fresh" style="margin-top:8px">Starter projections sum to {ta:.1f} vs {tb:.1f}; ESPN\'s team projections above may differ slightly. '
         f'Highlighted = higher {"actual" if started else "projected"} points at that slot.</div>')
    ai_button("Break down this matchup", "mu", f"Break down my week {snap.week} matchup against {opp.name}: where am I strong or weak, and what could swing it?", "Matchup breakdown", "scoreboard")
