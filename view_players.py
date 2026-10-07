"""Players: waiver wire and free-agent discovery."""
from __future__ import annotations

import streamlit as st

import ui
from ctx import Ctx
from optimizer import availability, can_start
from views_common import html, moves_block, player_list


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

    html(ui.section("Suggested moves", "from your strategy rules; same engine as the assistant"))
    moves_block(ctx, "pl")

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
    season = ctx.hub.season
    sid = lambda p: ctx.index.find(p) if ctx.index else None
    rows = [{"p": p, "ros": season.raw_ros(p), "key": season.rank_key(p), "trend": (ctx.trending.get(sid(p), 0) if sid(p) else 0), "tags": [t[0] for t in p.tags]} for p in ctx.fas]
    rows = [r for r in rows if pos in (None, "All", r["p"].position) and (not healthy or can_start(r["p"])) and (not tag or tag.lower() in r["tags"])
            and (not q or q.lower() in r["p"].name.lower() or q.lower() in r["p"].pro_team.lower())]
    key = {"This week": lambda r: r["p"].week_proj, "Trending": lambda r: (r["trend"], r["key"])}.get(sort, lambda r: r["key"])
    rows.sort(key=key, reverse=True)
    top = max((r["ros"] for r in rows), default=1) or 1
    html(f'<div class="fresh" style="margin:2px 0 8px">Showing {min(len(rows), 25)} of {len(rows)} · rest-of-season points = expected fantasy points over the games left '
         f'(byes, injuries and playoff weeks included), under your league scoring ({", ".join(f"{k.replace("points_per_", "").replace("_", " ")} {v:g}" for k, v in snap.scoring_notes.items())}).</div>')
    items = []
    for r in rows[:25]:
        p = r["p"]
        note = (" · trending" if r["trend"] else "")
        items.append((p, {"slot": "", "show_actual": False, "value_pct": 100 * r["ros"] / top, "value_label": f"{r['ros']:.0f}",
                          "note": f"{note} · {p.percent_owned:.0f}% owned" if p.percent_owned >= 0 else note}))
    player_list(ctx, "fa", items)
