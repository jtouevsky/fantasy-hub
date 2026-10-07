"""Trades v2: two separate questions (should I offer it / would they accept it), whole-league search, offer ladder, negotiation log."""
from __future__ import annotations

import time

import streamlit as st

import acceptance as acc
import db
import trading
import ui
from ctx import Ctx
from views_common import ai_button, html

_ME = {"good": ("good", "thumb_up"), "marginal": ("warn", "balance"), "no": ("bad", "thumb_down")}
_THEM = {"likely": ("good", "thumb_up"), "coin flip": ("warn", "help"), "unlikely": ("bad", "thumb_down")}
_POSITIONS = ["QB", "RB", "WR", "TE"]


def _trunc(s: str) -> str:
    return f'<span class="trunc">{ui.esc(s)}</span>'


def _player_tags(world: trading.TradeWorld, p) -> str:
    out = ""
    st_ = p.injury_status
    if st_ in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
        tl = world.season.timeline(p)
        label = f"{tl.status} · back ~wk {tl.return_week}" if tl.return_week else f"{tl.status} · likely out for the season"
        out += ui.chip(label, "warn", "personal_injury")
    out += ui.tag_chips(p)
    return out


def _side(world: trading.TradeWorld, b, players) -> str:
    return "".join(f'<div class="p" style="--tc:{b.color(p.pro_team)}">{b.avatar(p, 40)}<div style="min-width:0"><div class="nm">{_trunc(p.name)}</div>'
                   f'<div class="sub">{ui.chip(p.position, "pos")} {b.nfl_tag(p.pro_team)}</div>'
                   f'<div class="sub tags">{_player_tags(world, p)}</div></div></div>' for p in players)


def _weeks_row(world: trading.TradeWorld, ev: trading.TradeEval) -> str:
    reg = world.snap.reg_season_weeks
    moving = list(ev.give) + list(ev.get)
    cells = []
    for w, before, after in ev.my_weeks:
        d = after - before
        mark = "playoffs" if w > reg else ("bye" if any(p.bye_week == w for p in moving) else "")
        cells.append(f'<div class="wk {"up" if d > 0.05 else "dn" if d < -0.05 else ""}{" po" if w > reg else ""}" title="Week {w}: {before:.1f} to {after:.1f} expected points">'
                     f'<small>W{w}</small><b class="num">{d:+.1f}</b><i>{mark}</i></div>')
    return f'<div class="wkrow" role="img" aria-label="Weekly change in your expected lineup points">{"".join(cells)}</div>'


def _ladder(ev: trading.TradeEval) -> str:
    if not ev.ladder:
        return ""
    steps = []
    for i, s in enumerate(ev.ladder[:3]):
        kind, ic = _THEM[s.acceptance]
        steps.append(f'<li class="step"><span class="n">{i + 1}</span><div style="min-width:0"><b>{ui.esc(s.name)}</b>'
                     f'<div class="g">{_trunc(" + ".join(p.name for p in s.give))}</div><div class="n2">{ui.chip(s.acceptance.title(), kind, ic)}'
                     f'<span class="num">{s.my_delta:+.0f} for you</span></div><small>{ui.esc(s.note)}</small></div></li>')
    return f'<div class="ladder"><h5>Offer ladder</h5><ol>{"".join(steps)}</ol></div>'


def offer_card(ctx: Ctx, ev: trading.TradeEval) -> str:
    w, b = ctx.hub.world, ctx.brand
    mk, mi = _ME[ev.verdict_me], _THEM[ev.acceptance.label]
    a = ev.acceptance
    chips = ui.chip(ev.kind, "pos") + ui.chip(ev.verdict_me_text, mk[0], mk[1]) + ui.chip(f"{a.label.title()} to accept", mi[0], mi[1])
    if a.confirmed:
        chips += ui.chip("Confirmed by manager", "good", "verified")
    if ev.speculative:
        chips += ui.chip("Speculative", "warn", "bolt")
    reasons = "".join(f"<li>{ui.esc(r)}</li>" for r in a.reasons[:4])
    risk = "".join(f"<li>{ui.esc(r)}</li>" for r in trading.risk_lines(w, ev))
    notes = "".join(f"<li>{ui.esc(n)}</li>" for n in ev.notes if "Speculative" not in n)
    mine_share, theirs_share = ev.my_split, ev.market_split_theirs
    return (
        f'<article class="offer glass-med"><div class="fh-ctx" style="margin-bottom:12px">{chips}</div>'
        f'<div class="sides"><div class="col"><h5>You give</h5>{_side(w, b, ev.give)}</div><div class="swap">{ui.icon("swap_horiz")}</div>'
        f'<div class="col"><h5>You get from {_trunc(ev.other.name)}</h5>{_side(w, b, ev.get)}</div></div>'
        f'<div class="vals"><div class="val"><h6>My value <small>should I offer it?</small></h6>'
        f'<div class="big num {"up" if ev.my_delta > 0.5 else "dn" if ev.my_delta < -0.5 else ""}">{ev.my_delta:+.0f}</div><small>weighted points to your lineup, rest of season ({ev.my_avg_week:+.1f}/wk)</small>'
        f'<div class="track" role="img" aria-label="My value split {mine_share:.0f} to {100 - mine_share:.0f}"><i style="width:{mine_share:.0f}%"></i></div>'
        f'<div class="lbl"><span>You {mine_share:.0f}</span><span>{100 - mine_share:.0f} Them</span></div></div>'
        f'<div class="val"><h6>Market value <small>would they accept?</small></h6>'
        f'<div class="big num">{theirs_share:.0f}<small>% to him</small></div><small>what his league sees: ADP, consensus rank, ownership; plus his needs</small>'
        f'<div class="track m" role="img" aria-label="Market value split {100 - theirs_share:.0f} to {theirs_share:.0f}"><i style="width:{100 - theirs_share:.0f}%"></i></div>'
        f'<div class="lbl"><span>You {100 - theirs_share:.0f}</span><span>{theirs_share:.0f} Them</span></div></div></div>'
        f'<div class="wkhead">Your lineup, week by week <small>(expected points change; playoff weeks count 1.5x)</small></div>{_weeks_row(w, ev)}'
        f'<div class="why2"><div><h5>Why he might say {"yes" if a.plausible else "no"}</h5><ul>{reasons or "<li>No strong signals either way.</li>"}</ul></div>'
        f'<div><h5>Risk and notes</h5><ul>{risk}{notes or ""}{"" if (risk or notes) else "<li>Nothing unusual.</li>"}</ul></div></div>'
        f'{_ladder(ev)}'
        f'<div class="todo">{ui.icon("arrow_forward")}<span>Do this in the ESPN app: open {ui.esc(ev.other.name)}\'s team and propose this trade.</span></div></article>')


def _prompt(ev: trading.TradeEval) -> str:
    return (f"Evaluate this trade for me: I give {' + '.join(p.name for p in ev.give)} and get {' + '.join(p.name for p in ev.get)} from {ev.other.name}. "
            "Use evaluate_trade, answer 'should I offer it' and 'would they accept' separately, and show the offer ladder.")


def _log_popover(ctx: Ctx, ev: trading.TradeEval, key: str) -> None:
    with st.popover("Log his answer", icon=":material/edit_note:"):
        resp = st.radio("What did he say?", ["accepted", "rejected", "countered", "no response"], key=f"lr_{key}", horizontal=True)
        note = st.text_input("Note (optional)", key=f"ln_{key}", placeholder="e.g. wants a RB back")
        if st.button("Save", key=f"ls_{key}", icon=":material/check:"):
            acc.log_negotiation(ctx.cfg.db_path, ev.other.team_id, ev.other.owner_label or ev.other.name, ev.give, ev.get, resp, note, ev.acceptance.logit)
            ctx.hub.world.negs = acc.negotiations(ctx.cfg.db_path)
            st.toast("Logged. Future estimates for this manager will use it.")


def _show(ctx: Ctx, ev: trading.TradeEval, key: str) -> None:
    ctx.brand.prefetch(ev.give + ev.get)
    html(offer_card(ctx, ev))
    c1, c2, c3, c4 = st.columns([2.4, 2.2, 2, 2])
    with c1:
        ai_button("Ask AI about this", f"tr_{key}", _prompt(ev), "Trade review", "balance")
    with c2:
        with st.popover("Draft a message", icon=":material/chat:"):
            st.text_area("Pitch (edit, then send it yourself in ESPN)", trading.pitch(ctx.hub.world, ev), key=f"pitch_{key}", height=130)
            st.caption("Nothing is sent automatically.")
    with c3:
        _log_popover(ctx, ev, key)
    with c4:
        if st.button("Save to log", key=f"log_{key}", icon=":material/bookmark_add:"):
            db.log_recommendation("trade", f"{' + '.join(p.name for p in ev.give)} for {' + '.join(p.name for p in ev.get)} ({ev.other.name})",
                                  {"my_delta": ev.my_delta, "acceptance": ev.acceptance.label}, ctx.snap.week, "ui", ctx.cfg.db_path)
            st.toast("Saved to your recommendation log.")


# ---- natural-language request -> editable constraints ---------------------------------------------------------------
def _apply_text(ctx: Ctx) -> None:
    c = trading.parse_request(st.session_state.get("tr_text", ""), ctx.hub.world)
    ss, tid = st.session_state, {t.team_id: t for t in ctx.snap.teams}
    ss["tr_partner"] = _team_label(tid[c.partner]) if c.partner in tid else "Anyone in the league"
    ss["tr_split"] = int(c.target_split)
    ss["tr_want"] = sorted(c.want_positions)
    ss["tr_nogive"] = sorted(c.exclude_give_positions)
    ss["tr_need"] = c.need_position or "No requirement"
    ss["tr_loss"] = c.allow_loss
    mine = {p.player_id: p for p in ctx.me.roster}
    ss["tr_offer"] = [_pl(mine[i]) for i in c.offering if i in mine]
    ss["tr_parsed"] = c.notes


def _team_label(t) -> str:
    return f"{t.owners[0].first_name} · {t.name}" if t.owners and t.owners[0].first_name else t.name


def _pl(p) -> str:
    return f"{p.name} · {p.position} · {p.pro_team}"


def render(ctx: Ctx) -> None:
    snap, me, world = ctx.snap, ctx.me, ctx.hub.world
    others = [t for t in snap.teams if t.team_id != me.team_id]
    labels = {_team_label(t): t for t in others}
    ctx.brand.prefetch([], others)
    s = world.season
    mine = {_pl(p): p for p in sorted(me.roster, key=lambda p: -s.rank_key(p)) if p.position in _POSITIONS}
    mode = st.segmented_control("Mode", ["Find me a trade", "Evaluate a deal", "Negotiation log"], default="Find me a trade", key="tr_mode", label_visibility="collapsed")

    if "trade_partner" in st.session_state and st.session_state["trade_partner"] not in labels:
        st.session_state.pop("trade_partner")

    if mode == "Evaluate a deal":
        other = labels[st.selectbox("Trade with", list(labels), key="trade_partner", help="Search by owner first name or team name.")]
        theirs = {_pl(p): p for p in sorted(other.roster, key=lambda p: -s.rank_key(p)) if p.position in _POSITIONS}
        c1, c2 = st.columns(2)
        give = c1.multiselect("You give", list(mine), key="ev_give", placeholder="Choose your players")
        get = c2.multiselect("You get", list(theirs), key="ev_get", placeholder=f"Choose from {other.name}")
        if give and get:
            ev = trading.evaluate(world, other, [mine[g] for g in give], [theirs[g] for g in get])
            ev.ladder = trading.build_ladder(world, ev, trading.Constraints(), trading._my_pool(world, trading.Constraints()), [])
            _show(ctx, ev, "eval")
        else:
            html(ui.empty("Pick players on both sides", "I'll answer two separate questions: should you offer it, and would he accept.", "swap_horiz"))
        return

    if mode == "Negotiation log":
        _negotiation_ui(ctx, labels, mine)
        return

    # ---- find me a trade: type it, check how I read it, search the whole league ----
    html(f'<div class="fresh" style="margin-bottom:6px">Describe what you want in plain English, e.g. <i>find me a WR for the playoffs without giving up an RB, about 60/40</i>. '
         f'I turn it into the settings below so you can correct anything before searching.</div>')
    t1, t2 = st.columns([6, 1.4], vertical_alignment="bottom")
    t1.text_input("What trade are you looking for?", key="tr_text", placeholder="e.g. sell high on my RB for a receiver; no QBs", label_visibility="collapsed")
    t2.button("Read it", key="tr_read", icon=":material/auto_fix_high:", on_click=_apply_text, args=(ctx,))
    parsed = st.session_state.get("tr_parsed")
    if parsed:
        html(f'<div class="fh-ctx">{ui.chip("How I read that", "", "psychology")}{"".join(ui.chip(n, "") for n in parsed)}</div>')
    st.session_state.setdefault("tr_partner", "Anyone in the league")
    c1, c2, c3 = st.columns([3, 3, 2])
    partner = c1.selectbox("Trade with", ["Anyone in the league"] + list(labels), key="tr_partner")
    offer = c2.multiselect("Players I'd move (optional)", list(mine), key="tr_offer", placeholder="Let the search choose")
    split = c3.slider("My-value split", 50, 70, 60, key="tr_split", help="60 = I get 60% of the combined value to MY lineup. Market value stays near-even so he can say yes.")
    d1, d2, d3, d4 = st.columns([2, 2, 2, 2])
    want = d1.multiselect("Ask for", _POSITIONS, key="tr_want", placeholder="Any position")
    nogive = d2.multiselect("Won't give", _POSITIONS, key="tr_nogive", placeholder="None")
    need = d3.selectbox("Must help my", ["No requirement"] + _POSITIONS, key="tr_need")
    loss = d4.toggle("Sell / rebuild (lineup may dip)", key="tr_loss")
    c = trading.Constraints(partner=labels[partner].team_id if partner in labels else None, offering=[mine[o].player_id for o in offer], want_positions=set(want),
                            exclude_give_positions=set(nogive), need_position="" if need == "No requirement" else need, target_split=float(split), allow_loss=loss, max_results=6)
    html(f'<div class="fh-ctx">{"".join(ui.chip(x, "") for x in c.summary())}</div>')
    ck = (ctx.snap.fetched_at, repr(sorted(c.__dict__.items(), key=lambda kv: kv[0])), ctx.hub.strategy.accept_threshold, len(world.negs))
    if st.session_state.get("_tr_ck") != ck:
        with st.spinner("Scanning every team for the cheapest offer that works..."):
            st.session_state["_tr_res"], st.session_state["_tr_ck"] = trading.search(world, c), ck
    found = st.session_state["_tr_res"]
    if not found:
        html(ui.notice("No trade clears both questions (good for you AND plausible for him) under these settings. Loosen the split, drop a position filter, or allow a sell/rebuild move.", "warn", "search_off"))
        return
    html(ui.section(f"{len(found)} option{'s' if len(found) != 1 else ''}", "cheapest winning offer first"))
    for i, ev in enumerate(found):
        _show(ctx, ev, f"f{i}")


def _negotiation_ui(ctx: Ctx, labels: dict, mine: dict) -> None:
    world, s = ctx.hub.world, ctx.hub.season
    other = labels[st.selectbox("Manager", list(labels), key="neg_partner")]
    prof = acc.manager_profile(ctx.cfg.db_path, other, world.stats, world.market)
    lg = prof["logged"]
    html(f'<div class="fh-ctx">{ctx.brand.team_avatar(other, 28)}<b>{ui.esc(other.name)}</b>{ui.chip(other.record, "", "sports_score")}'
         f'{ui.chip(f"{prof["trades_this_season"]} trades this season", "", "swap_horiz")}{ui.chip(f"{prof["adds"]} adds · {prof["drops"]} drops", "", "person_add")}'
         f'{ui.chip(f"Logged: {lg["accepted"]} yes · {lg["rejected"]} no · {lg["countered"]} counter", "", "history")}</div>')
    html(ui.notice(f'Tendency: {ui.esc(prof["tendency_text"])}.', "", "psychology"))
    html(ui.section("Add an answer", "what he actually said"))
    theirs = {_pl(p): p for p in sorted(other.roster, key=lambda p: -s.rank_key(p)) if p.position in _POSITIONS}
    c1, c2 = st.columns(2)
    give = c1.multiselect("I offered", list(mine), key="neg_give", placeholder="My players")
    get = c2.multiselect("I asked for", list(theirs), key="neg_get", placeholder="His players")
    r1, r2, r3 = st.columns([2, 4, 1.4], vertical_alignment="bottom")
    resp = r1.selectbox("He said", ["accepted", "rejected", "countered", "no response"], key="neg_resp")
    note = r2.text_input("Note", key="neg_note", placeholder="Optional, e.g. 'would do it if I add a WR3'")
    if r3.button("Save", key="neg_save", icon=":material/check:", disabled=not (give and get)):
        ev = trading.evaluate(world, other, [mine[g] for g in give], [theirs[g] for g in get])
        acc.log_negotiation(ctx.cfg.db_path, other.team_id, other.owner_label or other.name, ev.give, ev.get, resp, note, ev.acceptance.logit)
        world.negs = acc.negotiations(ctx.cfg.db_path)
        st.toast("Logged.")
        st.rerun()
    html(ui.section("History"))
    rows = acc.negotiations(ctx.cfg.db_path, other.team_id)
    if not rows:
        html(ui.empty("Nothing logged with this manager yet", "Log what he says to your offers; confirmed answers override the estimate for that same ask.", "history"))
    for n in rows:
        kind = {"accepted": "good", "rejected": "bad", "countered": "warn"}.get(n["response"], "")
        html(f'<div class="neg">{ui.chip(n["response"].title(), kind)}<span><b>{ui.esc(n["give_names"])}</b> for <b>{ui.esc(n["get_names"])}</b>'
             f'{" · " + ui.esc(n["note"]) if n["note"] else ""}</span><small>{time.strftime("%b %-d", time.localtime(n["ts"]))}</small></div>')
