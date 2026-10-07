"""FastAPI backend. Read-only: nothing here can change anything on ESPN.

Every heavy result is computed once per data refresh (ctx.memo) so navigating between screens in the client never recomputes anything.
"""
from __future__ import annotations

import base64
import os
import time
from datetime import datetime
from typing import Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import acceptance as acc
import agent
import ai_runner
import assets
import ctx as cx
import db
import news as news_mod
import strategy as strategy_mod
import theme
import trading
import ui
from config import load_config
from edge import live as edge_live, odds as odds_mod, usage as edge_usage
from edge.settings import load_params
from edge.timing import timing_alerts
from league_client import LeagueConnectionError
from optimizer import availability, current_lineup
from server import serialize as S

app = FastAPI(title="Fantasy Hub API", docs_url="/api/docs", openapi_url="/api/openapi.json")
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "dist")


def get() -> cx.Ctx:
    try:
        return cx.get_ctx()
    except LeagueConnectionError as e:
        raise HTTPException(503, str(e))


@app.exception_handler(Exception)
async def boom(request: Request, exc: Exception):                   # one failed endpoint must not take the app down; keep the traceback for debugging
    import traceback
    os.makedirs("data", exist_ok=True)
    with open("data/last_error.log", "w") as f:
        f.write(f"{request.url}\n{traceback.format_exc()}")
    return JSONResponse({"error": f"{type(exc).__name__}: {str(exc)[:200]}"}, status_code=500)


# ------------------------------------------------------------------ bootstrap / settings
def _nfl_meta(cfg) -> dict:
    teams = assets.nfl_teams(cfg.db_path)
    try:
        geo = assets.logo_geometry(cfg.db_path)
    except Exception:
        geo = {}
    out = {}
    for ab, t in teams.items():
        dx, dy, k = assets.logo_transform(geo.get(ab))
        out[ab] = {"abbr": ab, "name": t.name, "short": t.short, "color": assets.usable_color(t.color), "logo": assets.team_logo(ab, cfg.db_path), "dx": dx, "dy": dy, "k": k}
    return out


@app.get("/api/bootstrap")
def bootstrap():
    cfg = load_config()
    mode, fav = theme.get_mode(cfg.db_path), theme.get_accent_team(cfg.db_path)
    base = {"demo": cx.using_demo(), "settings": {"mode": mode, "accentTeam": fav}, "nfl": _nfl_meta(cfg)}
    if not base["demo"] and cfg.missing_espn():
        return {**base, "setup": {"missing": cfg.missing_espn()}}
    try:
        c = get()
    except HTTPException as e:
        return {**base, "setup": {"problem": e.detail}}
    snap = c.snap
    accent = None
    if fav == "MY_TEAM":
        accent = S.FANTASY_COLORS[((cfg.team_id or 1) - 1) % len(S.FANTASY_COLORS)]
    elif fav:
        t = assets.team(fav, cfg.db_path)
        accent = assets.usable_color(t.color) if t.abbr != "NFL" else None
    teams = sorted(snap.teams, key=lambda t: t.standing)
    return {**base, "league": {"name": snap.league_name, "year": snap.year, "week": snap.week, "finalWeek": snap.final_week, "regWeeks": snap.reg_season_weeks, "teamCount": snap.team_count,
                               "slots": snap.starter_slots, "bench": snap.bench_slots, "ir": snap.ir_slots, "faab": snap.faab_budget, "waiverDays": snap.waiver_days, "scoring": snap.scoring_notes},
            "me": S.fteam(c, c.me), "teams": [S.fteam(c, t) for t in teams], "warnings": c.warnings, "age": S.age_seconds(c), "ttl": cfg.cache_ttl, "accent": accent,
            "accentInk": assets.on_color(accent) if accent else None, "scanStatus": c.scan_status, "edgeOn": c.edge is not None, "version": cx.STORE.get("version", 0),
            "search": [{"id": p.player_id, "name": p.name, "pos": p.position, "team": p.pro_team, "owner": (p.owner_team_id or 0)} for p in sorted(c.everyone().values(), key=lambda p: p.name)]}


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    cfg = load_config()
    if "mode" in body:
        theme.set_mode(body["mode"], cfg.db_path)
    if "accentTeam" in body:
        theme.set_accent_team(body["accentTeam"] or "", cfg.db_path)
    return {"ok": True}


@app.post("/api/refresh")
def refresh():
    cx.get_ctx(force=True)
    return {"ok": True, "version": cx.STORE.get("version", 0)}


@app.post("/api/demo")
def demo(body: dict = Body(...)):
    cx.set_demo(bool(body.get("on")))
    return {"ok": True}


@app.post("/api/watch/{pid}")
def watch(pid: int):
    c = get()
    now = cx.toggle_watch(pid, c.cfg.db_path)
    c.watchlist = cx.load_watchlist(c.cfg.db_path)
    return {"watching": now}


@app.get("/api/img/fteam/{tid}")
def fteam_logo(tid: int):
    c = get()
    t = c.snap.team(tid)
    if not t or not t.logo:
        raise HTTPException(404)
    cookies = {"espn_s2": c.cfg.espn_s2, "SWID": c.cfg.swid} if not c.demo and c.cfg.espn_s2 else None
    src = assets.fantasy_logo_src(t.logo, cookies, c.cfg.db_path)
    if not src:
        raise HTTPException(404)
    hdr = {"Cache-Control": "public, max-age=86400"}
    if src.startswith("data:"):
        head, b64 = src.split(",", 1)
        return Response(base64.b64decode(b64), media_type=head[5:].split(";")[0], headers=hdr)
    return RedirectResponse(src, headers=hdr)


# ------------------------------------------------------------------ overview / team / matchup / league
def _blocks(c: cx.Ctx) -> list[dict]:
    me = c.me
    mine = {p.player_id: p for p in me.roster}
    out: list[dict] = []
    for a in timing_alerts(me.roster, c.edge):
        out.append({"kind": "alert", "tone": "warn" if a["severity"] == "watch" else "bad", "title": "Re-check before lock" if a["kind"] == "gtd" else "Teammate watch", "text": a["message"]})
    starting = {p.player_id for p in me.roster if p.lineup_slot not in ("BE", "IR")}
    relevant = [ev for ev in c.events if ev.get("player_espn_id") in mine and (ev.get("status") not in (None, "active") or
                                                                              (ev.get("event_type") in ("role_change", "depth_chart", "suspension") and ev.get("player_espn_id") in starting))]
    out += [{"kind": "event", "event": S.news_event(ev)} for ev in relevant[:4]]
    if c.edge:
        for cas in c.edge.cascades:
            for ben in cas["beneficiaries"]:
                if ben.get("espn_id") in mine and abs(ben["weekly_pts"]) >= 1.5:
                    applied = ben.get("applied")
                    out.append({"kind": "cascade", "tone": "", "title": "Edge" if applied else "Opportunity context (not in projections)", "text": ben["reason"]})
                    break
    return out


@app.get("/api/overview")
def overview():
    c = get()
    snap, me = c.snap, c.me
    plan = c.plan()
    starters = [p for p in me.roster if p.lineup_slot not in ("BE", "IR")]
    nxt = sorted((p for p in starters if ui.lock_state(p) == "open"), key=lambda p: ui.kickoff(p))
    ordered = snap.standings()
    idx = next((i for i, t in enumerate(ordered) if t.team_id == me.team_id), 0)
    ms = c.memo("moves3", lambda: c.hub.moves.find_moves(3))
    return {
        "scoreboard": S.scoreboard(c), "age": S.age_seconds(c), "ttl": c.cfg.cache_ttl,
        "ready": not plan.swaps and not plan.warnings, "swapCount": len(plan.swaps),
        "nextLock": {"label": ui.kick_label(nxt[0]), "name": nxt[0].name} if nxt else None,
        "locked": sum(1 for p in starters if ui.lock_state(p) == "locked"), "emptySlots": sum(1 for _, p in plan.current if p is None),
        "waiverRank": me.waiver_rank, "faabLeft": int(snap.faab_budget - me.faab_spent) if snap.faab_budget else None,
        "scanStatus": c.scan_status, "blocks": _blocks(c), "hasEvents": bool(c.events),
        "swaps": [S.swap(c, s) for s in plan.swaps[:3]], "planWarnings": plan.warnings[:2], "moves": S.moveset(c, ms),
        "standings": [S.fteam(c, t) for t in ordered[max(0, idx - 2): idx + 3]],
        "top": [S.player(c, p) for p in sorted(starters, key=lambda p: -p.week_proj)[:3]],
    }


@app.get("/api/team")
def team():
    c = get()
    snap, me = c.snap, c.me
    plan = c.plan()
    cur_ids = {p.player_id for _, p in plan.current if p}
    opt_ids = {p.player_id for _, p in plan.optimal if p}

    def rows(src):
        return [{"slot": slot, "p": S.player(c, p, slot) if p else None} for slot, p in src]

    start_ids = {p.player_id for _, p in plan.current if p}
    bench = [p for p in me.roster if p.lineup_slot not in ("IR",) and p.player_id not in start_ids]
    ir = [p for p in me.roster if p.lineup_slot == "IR"]
    return {
        "currentTotal": round(plan.current_total, 1), "optimalTotal": round(plan.optimal_total, 1), "gain": round(plan.gain, 1), "hasSwaps": bool(plan.swaps),
        "edgesOn": any(p.has_edge for p in me.roster), "espnOptimal": round(plan.espn_optimal_total, 1), "slotsTotal": sum(snap.starter_slots.values()),
        "alerts": [{"tone": "bad" if a["severity"] == "act" else "warn", "text": a["message"]} for a in timing_alerts(me.roster, c.edge)],
        "current": rows(plan.current), "optimal": rows(plan.optimal), "movedIn": sorted(opt_ids - cur_ids), "movedOut": sorted(cur_ids - opt_ids),
        "bench": [S.player(c, p, "BN") for p in sorted(bench, key=lambda p: -availability(p))], "benchSlots": snap.bench_slots,
        "ir": [S.player(c, p, "IR") for p in ir], "irSlots": snap.ir_slots, "swaps": [S.swap(c, s) for s in plan.swaps],
    }


@app.get("/api/matchup")
def matchup():
    c = get()
    snap, me, opp = c.snap, c.me, c.opp
    sb = S.scoreboard(c)
    if not sb:
        return {"scoreboard": None}
    started = sb["state"] != "Pregame"
    a_rows, b_rows = current_lineup(me.roster, snap.starter_slots), current_lineup(opp.roster, snap.starter_slots)
    remaining = lambda rows: sum(1 for _, p in rows if p and ui.lock_state(p) == "open")
    envs, seen = [], set()
    if c.edge and c.edge.game_env:
        for tm in sorted({p.pro_team for _, p in a_rows + b_rows if p and p.position != "D/ST"}):
            env = c.edge.game_env.get(tm)
            if env and frozenset((env.team, env.opp)) not in seen:
                seen.add(frozenset((env.team, env.opp)))
                envs.append(S.game_env(env))
    duels = []
    for (slot, pa), (_, pb) in zip(a_rows, b_rows):
        wa = bool(pa and pb and ((pa.week_points > pb.week_points) if started else (pa.week_proj > pb.week_proj)))
        wb = bool(pa and pb and ((pb.week_points > pa.week_points) if started else (pb.week_proj > pa.week_proj)))
        duels.append({"slot": slot, "a": S.player(c, pa) if pa else None, "b": S.player(c, pb) if pb else None, "winA": wa, "winB": wb})
    return {"scoreboard": sb, "age": S.age_seconds(c), "ttl": c.cfg.cache_ttl, "started": started, "demo": c.demo, "remainingA": remaining(a_rows), "remainingB": remaining(b_rows),
            "envs": envs, "duels": duels, "sumA": round(sum(p.week_proj for _, p in a_rows if p), 1), "sumB": round(sum(p.week_proj for _, p in b_rows if p), 1)}


@app.get("/api/league")
def league():
    c = get()
    snap = c.snap
    ms = []
    for m in snap.matchups:
        a, b = snap.team(m.home_team_id), snap.team(m.away_team_id)
        if a and b:
            ms.append({"a": S.fteam(c, a), "b": S.fteam(c, b), "aProj": round(m.home_proj, 1), "bProj": round(m.away_proj, 1)})
    return {"week": snap.week, "regWeeks": snap.reg_season_weeks, "count": snap.team_count, "standings": [S.fteam(c, t) for t in snap.standings()], "matchups": ms}


# ------------------------------------------------------------------ players / waivers
@app.get("/api/players")
def players():
    c = get()
    season = c.hub.season
    ms = c.memo("moves3", lambda: c.hub.moves.find_moves(3))
    def trend(p):
        sid = c.index.find(p) if c.index else None
        return c.trending.get(sid, 0) if sid else 0
    fas = []
    for p in c.fas:
        d = S.player(c, p, "")
        d.update({"ros": round(season.raw_ros(p)), "key": round(season.rank_key(p), 1), "trend": trend(p), "healthy": not p.is_out and not p.on_bye})
        fas.append(d)
    watched = [S.player(c, p, "") | {"where": ("your team" if (o := c.owner_of(p)) and o.team_id == c.me.team_id else f"on {o.name}" if o else "free agent")}
               for pid in sorted(c.watchlist) if (p := c.everyone().get(pid))]
    me = c.me
    return {"moves": S.moveset(c, ms), "fas": fas, "watch": watched, "waiverRank": me.waiver_rank, "faabLeft": int(c.snap.faab_budget - me.faab_spent) if c.snap.faab_budget else None,
            "faab": c.snap.faab_budget, "waiverDays": c.snap.waiver_days, "hasTags": any(p.tags for p in c.fas), "positions": sorted({p.position for p in c.fas})}


# ------------------------------------------------------------------ player sheet
@app.get("/api/player/{pid}")
def player_detail(pid: int):
    c = get()
    p = c.everyone().get(pid)
    if p is None:
        raise HTTPException(404, "That player isn't in the current data. Try Refresh.")
    snap, m = c.snap, c.model
    season = c.hub.season
    owner = c.owner_of(p)
    d = S.player(c, p, detail=True)
    team = assets.team(p.pro_team, c.cfg.db_path)
    d["nflName"] = team.name
    d.update({"ppg": round(m.ppg(p), 1), "ros": round(season.raw_ros(p)), "tl": season.timeline(p).note if p.injury_status in ("INJURY_RESERVE", "OUT", "SUSPENSION", "DOUBTFUL", "QUESTIONABLE") else "",
              "ownerTeam": S.fteam(c, owner) if owner else None, "weekLabel": (f"vs {p.opponent}, {ui.kick_label(p)}" if p.opponent else ("bye week" if p.on_bye else "no game info")),
              "edgeLabel": ui.edge_label(p), "week": snap.week})
    gsis = c.edge.gsis_of.get(p.player_id) if c.edge else None
    d["usage"] = []
    if gsis and not c.demo:
        try:
            cells = edge_usage.usage_cells(edge_usage.usage_summary(edge_live.get_hist(snap.year, c.cfg.db_path), gsis, snap.year, snap.year * 100 + snap.week), p.position)
            d["usage"] = [{"value": v, "label": lab, "hint": hint} for v, lab, hint in cells]
        except Exception:
            pass
    d["env"] = S.game_env(c.edge.game_env.get(p.pro_team)) if c.edge is not None else None
    d["edgeChecked"] = c.edge is not None and p.position in ("QB", "RB", "WR", "TE") and not p.on_bye
    d["events"] = [S.news_event(e) for e in c.events if e.get("player_espn_id") == pid][:2]
    # what you could do
    todo: dict = {"mode": "mine" if owner and owner.team_id == c.me.team_id else "fa" if owner is None else "other"}
    if todo["mode"] == "mine":
        plan = c.plan()
        occupied = [(s, q) for s, q in plan.current if q and q.player_id != p.player_id and s in p.eligible_slots]
        todo["starting"] = p.lineup_slot not in ("BE", "IR")
        todo["onIR"] = p.lineup_slot == "IR"
        todo["compare"] = [{"slot": s, "name": q.name, "theirs": round(availability(q), 1), "mine": round(availability(p), 1)} for s, q in occupied] if not todo["onIR"] and occupied else []
    elif todo["mode"] == "fa":
        mv = c.hub.moves
        cands = [mv.evaluate_move(p, dd) for dd in mv.drop_candidates(p)]
        ok = sorted((x for x in cands if x.ok), key=lambda x: -x.score)
        todo["move"] = S.move(c, ok[0]) if ok else None
        todo["why"] = None if ok else next((x.blocked[0] for x in cands if x.blocked), "Adding him wouldn't clearly improve your lineup this week or for the rest of the season.")
    return {**d, "todo": todo, "scoring": ", ".join(f"{k.replace('points_per_', '').replace('_', ' ')} {v:g}" for k, v in snap.scoring_notes.items())}


@app.get("/api/player/{pid}/history")
def player_history(pid: int):
    c = get()
    p = c.everyone().get(pid)
    if p is None:
        raise HTTPException(404)
    key = ("hist", pid)
    hist = c.memo(key, lambda: c.history(p))
    return {"demo": c.demo, "history": hist, "season": c.snap.year, "week": c.snap.week, "proj": 0 if p.on_bye else round(p.week_proj, 1)}


@app.get("/api/player/{pid}/news")
def player_news(pid: int):
    c = get()
    p = c.everyone().get(pid)
    fetch = c.news_fetch()
    if p is None or fetch is None:
        return {"available": False, "items": []}
    def go():
        pn = news_mod.get_player_news(p, fetch, c.index, db_path=c.cfg.db_path)
        return {"available": True, "injury": pn.injury_line, "injuryNotes": pn.sleeper.get("injury_notes", "") if pn.sleeper else "",
                "items": [{"headline": i.headline, "story": i.story[:420] + ("..." if len(i.story) > 420 else ""), "source": i.source, "published": i.published[:10]} for i in pn.items[:3]]}
    return c.memo(("pn", pid), go)


# ------------------------------------------------------------------ trades
def _fmt_tl(c: cx.Ctx, p) -> Optional[str]:
    if p.injury_status in ("INJURY_RESERVE", "OUT", "SUSPENSION"):
        tl = c.hub.season.timeline(p)
        return f"{tl.status} · back ~wk {tl.return_week}" if tl.return_week else f"{tl.status} · likely out for the season"
    return None


def _tp(c: cx.Ctx, p) -> dict:
    return {**S.player(c, p), "tl": _fmt_tl(c, p)}


def trade_view(c: cx.Ctx, ev: trading.TradeEval) -> dict:
    w = c.hub.world
    a = ev.acceptance
    reg = w.snap.reg_season_weeks
    moving = list(ev.give) + list(ev.get)
    weeks = [{"w": wk, "before": round(b, 1), "after": round(af, 1), "d": round(af - b, 1), "mark": "playoffs" if wk > reg else ("bye" if any(p.bye_week == wk for p in moving) else "")}
             for wk, b, af in ev.my_weeks]
    return {"kind": ev.kind, "other": S.fteam(c, ev.other), "give": [_tp(c, p) for p in ev.give], "get": [_tp(c, p) for p in ev.get],
            "verdictMe": ev.verdict_me, "verdictMeText": ev.verdict_me_text, "label": a.label, "confirmed": a.confirmed, "speculative": ev.speculative,
            "myDelta": round(ev.my_delta), "myAvgWeek": round(ev.my_avg_week, 1), "mySplit": round(ev.my_split), "marketTheirs": round(ev.market_split_theirs), "weeks": weeks,
            "signals": [{"name": x.name, "effect": round(x.contribution, 2), "text": x.text} for x in sorted(a.signals, key=lambda x: -abs(x.contribution))],
            "risk": trading.risk_lines(w, ev), "notes": [n for n in ev.notes if "Speculative" not in n],
            "ladder": [{"name": s.name, "give": [p.name for p in s.give], "label": s.acceptance, "myDelta": round(s.my_delta), "note": s.note} for s in ev.ladder[:3]],
            "pitch": trading.pitch(w, ev), "logit": a.logit, "giveIds": [p.player_id for p in ev.give], "getIds": [p.player_id for p in ev.get]}


@app.get("/api/trades/meta")
def trades_meta():
    c = get()
    s = c.hub.season
    pl = lambda p: {"id": p.player_id, "name": p.name, "pos": p.position, "team": p.pro_team}
    return {"teams": [{**S.fteam(c, t), "players": [pl(p) for p in sorted(t.roster, key=lambda p: -s.rank_key(p)) if p.position in trading.TRADEABLE]}
                      for t in c.snap.teams], "mine": [pl(p) for p in sorted(c.me.roster, key=lambda p: -s.rank_key(p)) if p.position in trading.TRADEABLE],
            "strategy": {"acceptThreshold": c.hub.strategy.accept_threshold}}


def _constraints(b: dict) -> trading.Constraints:
    return trading.Constraints(partner=b.get("partner"), offering=list(b.get("offering") or []), get_ids=list(b.get("getIds") or []), want_positions=set(b.get("want") or []),
                               exclude_give_positions=set(b.get("nogive") or []), need_position=b.get("need") or "", target_split=float(b.get("split", 60)),
                               allow_loss=bool(b.get("loss")), max_results=int(b.get("max", 6)))


@app.post("/api/trades/parse")
def trades_parse(body: dict = Body(...)):
    c = get()
    k = trading.parse_request(body.get("text", ""), c.hub.world)
    return {"partner": k.partner, "offering": k.offering, "split": k.target_split, "want": sorted(k.want_positions), "nogive": sorted(k.exclude_give_positions),
            "need": k.need_position, "loss": k.allow_loss, "notes": k.notes}


@app.post("/api/trades/search")
def trades_search(body: dict = Body(...)):
    c = get()
    k = _constraints(body)
    key = ("trades", repr(sorted(k.__dict__.items(), key=lambda kv: kv[0])), len(c.hub.world.negs))
    def go():
        res = trading.search(c.hub.world, k)
        return {"constraints": k.summary(), "results": [trade_view(c, ev) for ev in res]}
    return c.memo(key, go)


@app.post("/api/trades/evaluate")
def trades_eval(body: dict = Body(...)):
    c = get()
    w = c.hub.world
    byid = w.players()
    other = c.snap.team(body["partner"])
    give, get_ = [byid[i] for i in body["give"]], [byid[i] for i in body["get"]]
    ev = trading.evaluate(w, other, give, get_)
    ev.ladder = trading.build_ladder(w, ev, trading.Constraints(), trading._my_pool(w, trading.Constraints()), [])
    return trade_view(c, ev)


@app.get("/api/trades/negotiations")
def negotiations(team: int):
    c = get()
    other = c.snap.team(team)
    prof = acc.manager_profile(c.cfg.db_path, other, c.hub.world.stats, c.hub.world.market)
    rows = acc.negotiations(c.cfg.db_path, team)
    return {"team": S.fteam(c, other), "profile": {k: prof[k] for k in ("trades_this_season", "adds", "drops", "logged", "tendency_text")},
            "rows": [{"id": n["id"], "give": n["give_names"], "get": n["get_names"], "response": n["response"], "note": n["note"], "ts": time.strftime("%b %-d", time.localtime(n["ts"]))} for n in rows]}


@app.post("/api/trades/negotiations")
def add_negotiation(body: dict = Body(...)):
    c = get()
    w = c.hub.world
    byid = w.players()
    other = c.snap.team(body["team"])
    give, get_ = [byid[i] for i in body["give"]], [byid[i] for i in body["get"]]
    ev = trading.evaluate(w, other, give, get_)
    acc.log_negotiation(c.cfg.db_path, other.team_id, other.owner_label or other.name, give, get_, body["response"], body.get("note", ""), ev.acceptance.logit)
    w.negs = acc.negotiations(c.cfg.db_path)
    c._memo = {k: v for k, v in c._memo.items() if not (isinstance(k, tuple) and k[0] == "trades")}
    return {"ok": True}


@app.post("/api/recommendations")
def save_recommendation(body: dict = Body(...)):
    c = get()
    db.log_recommendation(body.get("kind", "trade"), body["summary"][:500], body.get("details") or {}, c.snap.week, "ui", c.cfg.db_path)
    return {"ok": True}


# ------------------------------------------------------------------ strategy / more
@app.get("/api/strategy")
def get_strategy():
    from dataclasses import asdict
    c = get()
    s = c.hub.strategy
    return {"strategy": asdict(s), "slots": c.snap.starter_slots, "caps": s.caps(c.snap.starter_slots), "streaming": sorted(s.streaming), "hasK": bool(c.snap.starter_slots.get("K"))}


@app.put("/api/strategy")
def put_strategy(body: dict = Body(...)):
    from dataclasses import fields
    c = get()
    known = {f.name for f in fields(strategy_mod.Strategy)}
    cur = c.hub.strategy
    new = strategy_mod.Strategy(**{**cur.__dict__, **{k: v for k, v in body.items() if k in known and k != "extra"}})
    strategy_mod.save(new, c.cfg.db_path)
    cx.invalidate()
    return {"ok": True}


@app.get("/api/news")
def news_feed():
    c = get()
    fetch = c.news_fetch()
    if fetch is None:
        return {"available": False}
    def go():
        teams = [("My team", c.me)] + ([("Opponent", c.opp)] if c.opp else [])
        data = {t.team_id: news_mod.collect_team_news(t, fetch, c.index, c.cfg.db_path) for _, t in teams}
        alerts = []
        for label, t in teams:
            for a in news_mod.lineup_alerts(c.snap, t, data[t.team_id]):
                alerts.append({"sev": a.severity, "msg": a.message, "action": a.action if label == "My team" else "", "who": "" if label == "My team" else t.name})
        groups = []
        for label, t in teams:
            items = []
            for p in t.roster:
                pn = data[t.team_id][p.player_id]
                if pn.items or pn.injury_line:
                    items.append({"p": S.player(c, p), "injury": pn.injury_line,
                                  "items": [{"headline": i.headline, "story": i.story[:420], "source": i.source, "published": i.published[:10]} for i in pn.items[:4]]})
            groups.append({"label": f"{label}: {t.name}", "items": items})
        return {"available": True, "alerts": alerts, "groups": groups}
    return c.memo("news", go)


@app.get("/api/edge")
def edge_page():
    c = get()
    e = c.edge
    if e is None:
        return {"on": False}
    params = load_params()
    ds = dict(e.data_status)
    q = odds_mod.quota(c.cfg.db_path)
    if q["remaining"]:
        ds["odds_quota"] = f"The Odds API credits remaining: {q['remaining']}"
    pls = [p for t in c.snap.teams for p in t.roster] + list(c.fas)
    adj = sorted((p for p in pls if p.has_edge), key=lambda p: -abs(p.edge_total))[:25]
    envs = {frozenset((x.team, x.opp)): x for x in e.game_env.values()}
    return {"on": True, "summary": params.get("summary"), "live": params.get("live_scale", {}),
            "modules": [{"key": k, "decision": v.get("decision", "?"), "alpha": v.get("alpha", 0)} for k, v in params.get("modules", {}).items()],
            "status": [{"k": k.replace("_", " "), "v": v} for k, v in ds.items()], "scan": c.scan_status,
            "cascades": [{"team": cc["team"], "absent": ", ".join(f'{a["name"]} ({a["status"]}{", long-term" if a["long_term"] else ""}; p(out) {a["p_out"]:.0%})' for a in cc["absent"][:4]),
                          "lines": [b["reason"] for b in sorted(cc["beneficiaries"], key=lambda b: -abs(b["weekly_pts"]))[:3]]}
                         for cc in sorted(e.cascades, key=lambda cc: -max((abs(b["weekly_pts"]) for b in cc["beneficiaries"]), default=0))[:8]],
            "adjustments": [{"p": S.player(c, p), "label": ui.edge_label(p), "reason": max(p.edge, key=lambda a: abs(a["delta"]))["reason"]} for p in adj],
            "envs": [S.game_env(x) for x in envs.values()], "events": [S.news_event(ev) for ev in c.events[:10]], "eventCount": len(c.events)}


@app.get("/api/log")
def rec_log():
    c = get()
    rows = db.list_recommendations(200, c.cfg.db_path)
    return {"rows": [{"id": r["id"], "kind": r["kind"], "source": r["source"], "outcome": r["outcome"], "week": r["week"], "summary": r["summary"][:420],
                      "when": time.strftime("%b %-d, %-I:%M %p", time.localtime(r["created_at"]))} for r in rows[:60]]}


@app.put("/api/log/{rid}")
def set_outcome(rid: int, body: dict = Body(...)):
    db.set_outcome(rid, body.get("outcome", ""), load_config().db_path)
    return {"ok": True}


# ------------------------------------------------------------------ assistant
def _chat_state() -> dict:
    return cx.STORE.setdefault("chat", {"api": [], "session": None, "ui": []})


@app.get("/api/chat")
def chat_get():
    c = get()
    return {"messages": _chat_state()["ui"], "chips": [{"text": t, "icon": i} for t, i in ai_runner.context_chips(c)], "backend": c.cfg.chat_backend}


@app.delete("/api/chat")
def chat_clear():
    cx.STORE["chat"] = {"api": [], "session": None, "ui": []}
    return {"ok": True}


def _trace(res) -> list[dict]:
    out = []
    for t in res.tool_trace:
        item = {"tool": t["tool"], "input": str(t["input"])[:140], "error": t["error"]}
        if t["tool"] == "find_moves" and not t["error"]:
            item["moves"] = t["result"]
        out.append(item)
    return out


@app.post("/api/chat")
def chat_send(body: dict = Body(...)):
    c = get()
    st = _chat_state()
    prompt = body["prompt"]
    try:
        res = ai_runner.run(c, prompt, st["session"], st["api"])
    except ai_runner.AIUnavailable as e:
        raise HTTPException(503, str(e))
    st["api"], st["session"] = res.history, res.session_id
    st["ui"] += [{"role": "user", "text": prompt, "trace": []}, {"role": "assistant", "text": res.text, "trace": _trace(res)}]
    return {"messages": st["ui"]}


@app.post("/api/ai")
def ai_oneshot(body: dict = Body(...)):
    """Contextual AI review (the 'Ask AI' buttons): a fresh conversation, not added to the chat history."""
    c = get()
    try:
        res = ai_runner.run(c, body["prompt"], None, [])
    except ai_runner.AIUnavailable as e:
        raise HTTPException(503, str(e))
    return {"text": res.text, "trace": _trace(res)}


# ------------------------------------------------------------------ static frontend (production build)
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = os.path.join(DIST, path)
        return FileResponse(f if path and os.path.isfile(f) else os.path.join(DIST, "index.html"))
