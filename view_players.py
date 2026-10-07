"""Players: waiver wire and free-agent discovery."""
from __future__ import annotations

import streamlit as st

import ui
import waivers
from ctx import Ctx
from optimizer import availability, can_start
from views_common import ai_button, html, move_gain, player_list


def render(ctx: Ctx) -> None:
    snap, me, b = ctx.snap, ctx.me, ctx.brand
    if not ctx.fas:
        html(ui.empty("Free agents aren't available right now", "ESPN didn't return the waiver pool. Try Refresh.", "cloud_off"))
        return
    chips = [ui.chip(f"Waiver priority #{me.waiver_rank}", "", "format_list_numbered")] if me.waiver_rank else []
    if snap.faab_budget:
        chips.append(ui.chip(f"FAAB ${int(snap.faab_budget - me.faab_spent)} of ${snap.faab_budget}", "", "payments"))
    if snap.waiver_days:
        chips.append(ui.chip("Waivers run " + ", ".join(d.title()[:3] for d in snap.waiver_days), "", "event"))
    html(f'<div class="fh-ctx">{"".join(chips)}</div>')

    html(ui.section("Suggested moves", "scored by re-solving your lineup"))
    sugg = waivers.suggest_add_drops(snap, ctx.model, ctx.fas, ctx.index, ctx.trending, 4)
    if not sugg:
        html(ui.notice("No add/drop is clearly worth making right now.", "good", "check_circle"))
    for i, s in enumerate(sugg):
        html(b.rec_card(f"Add {s.add.name}, drop {s.drop.name}", ui.esc(s.reason), ic="person_add", gain=move_gain(s)[0], gain_label=move_gain(s)[1],
                        why=f"{s.add.position} · {s.add.pro_team} · {s.weekly_gain:+.1f} this week" + (" · trending on Sleeper" if s.trending_adds else ""),
                        todo=s.action(), players=[s.add, s.drop]))
        c1, _ = st.columns([2.4, 5])
        with c1:
            ai_button("Ask AI why", f"pl_{i}", f"Should I add {s.add.name} and drop {s.drop.name}? Use suggest_waiver_moves and the news.", "Waiver move review")

    watched = [p for pid in sorted(ctx.watchlist) if (p := ctx.everyone().get(pid))]
    if watched:
        html(ui.section("Watchlist", f"{len(watched)} saved player{'s' if len(watched) != 1 else ''}"))
        def where(p):
            o = ctx.owner_of(p)
            return " · on your team" if o and o.team_id == me.team_id else f" · on {o.name}" if o else " · free agent"
        player_list(ctx, "watch", [(p, {"slot": "", "show_actual": False, "note": where(p)}) for p in watched])
    html(ui.section("Browse free agents"))
    f1, f2 = st.columns([3, 2], vertical_alignment="bottom")
    positions = sorted({p.position for p in ctx.fas})
    with f1:
        pos = st.pills("Position", ["All"] + positions, default="All", key="pl_pos")
    with f2:
        sort = st.segmented_control("Sort by", ["Rest of season", "This week", "Trending"], default="Rest of season", key="pl_sort")
    g1, g2 = st.columns([3, 2], vertical_alignment="center")
    with g1:
        q = st.text_input("Search free agents", key="pl_q", placeholder="Search by name or team", icon=":material/search:")
    with g2:
        healthy = st.toggle("Only healthy, not on bye", key="pl_healthy", value=False)

    tag = st.pills("Edge tag", ["Buy low", "Sell high", "Role growing"], key="pl_tag", help="From expected-points vs actual production (backtested: buy-low and sell-high predict the next game; role-growing is informational).") if any(p.tags for p in ctx.fas) else None
    ranks = waivers.rank_free_agents(ctx.model, ctx.fas, ctx.index, ctx.trending)
    ranks = [r for r in ranks if pos in (None, "All", r.player.position) and (not healthy or can_start(r.player)) and (not tag or tag.lower() in r.tags)
             and (not q or q.lower() in r.player.name.lower() or q.lower() in r.player.pro_team.lower())]
    key = {"This week": lambda r: r.week_value, "Trending": lambda r: (r.trending_adds, r.ros_value)}.get(sort, lambda r: r.ros_value)
    ranks.sort(key=key, reverse=True)
    top = max((r.ros_value for r in ranks), default=1) or 1
    html(f'<div class="fresh" style="margin:2px 0 8px">Showing {min(len(ranks), 25)} of {len(ranks)} · ROS value = points above a free replacement over the rest of the season, '
         f'under your league scoring ({", ".join(f"{k.replace("points_per_", "").replace("_", " ")} {v:g}" for k, v in snap.scoring_notes.items())}).</div>')
    items = []
    for r in ranks[:25]:
        note = (" · trending" if r.trending_adds else "") + (" · breakout" if r.breakout else "")
        items.append((r.player, {"slot": "", "show_actual": False, "value_pct": 100 * r.ros_value / top, "value_label": f"{r.ros_value:.0f}",
                                 "note": f"{note} · {r.player.percent_owned:.0f}% owned" if r.player.percent_owned >= 0 else note}))
    player_list(ctx, "fa", items)
