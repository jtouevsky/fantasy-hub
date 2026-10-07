"""League: standings and this week's slate."""
from __future__ import annotations

import ui
from ctx import Ctx
from views_common import html


def render(ctx: Ctx) -> None:
    snap, b = ctx.snap, ctx.brand
    b.prefetch([], snap.teams)
    html(ui.section("Standings", f"{snap.team_count} teams · {snap.reg_season_weeks}-game regular season"))
    rows = []
    for t in snap.standings():
        mine = t.team_id == ctx.me.team_id
        po = f'<div class="stat hide-sm"><b>{t.playoff_pct:.0f}%</b><small>Playoffs</small></div>' if t.playoff_pct else '<div class="stat hide-sm"></div>'
        rows.append(f'<div class="row" style="grid-template-columns:28px minmax(0,1fr) auto auto auto;{"background:var(--hover);" if mine else ""}">'
                    f'<span class="num" style="font-weight:700;color:var(--ink-3)">{t.standing}</span>'
                    f'<div class="who">{b.team_avatar(t, 40)}<div style="min-width:0"><div class="nm">{ui.esc(t.name)}{" " + ui.chip("You", "info") if mine else ""}</div>'
                    f'<div class="sub">{ui.esc(t.owner_label)}</div></div></div>'
                    f'<div class="stat"><b>{ui.esc(t.record)}</b><small>Record</small></div>'
                    f'<div class="stat hide-sm"><b>{t.points_for:.0f}</b><small>PF</small></div>{po}</div>')
    html(f'<div class="rows solid" role="list">{"".join(rows)}</div>')
    html(ui.section(f"Week {snap.week} matchups", "ESPN projections"))
    cards = []
    for m in snap.matchups:
        a, c = snap.team(m.home_team_id), snap.team(m.away_team_id)
        if not (a and c):
            continue
        cards.append(f'<div class="duel"><div class="half" style="justify-content:flex-start">{b.team_avatar(a, 38)}<div style="min-width:0"><div class="nm">{ui.esc(a.name)}</div>'
                     f'<div class="fresh">{ui.esc(a.owner_label)}</div></div><div class="stat"><b>{m.home_proj:.1f}</b></div></div><div class="mid">VS</div>'
                     f'<div class="half r">{b.team_avatar(c, 38)}<div style="min-width:0"><div class="nm">{ui.esc(c.name)}</div><div class="fresh">{ui.esc(c.owner_label)}</div></div>'
                     f'<div class="stat"><b>{m.away_proj:.1f}</b></div></div></div>')
    html(f'<div class="rows solid">{"".join(cards)}</div>' if cards else ui.empty("No matchups loaded", "", "event_busy"))
