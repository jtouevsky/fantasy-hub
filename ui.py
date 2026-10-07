"""HTML component builders (rendered with st.html). Pure functions: data in, markup out.

Branding comes from assets.py by stable IDs. Missing photos/logos always fall back to initials.
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Iterable, Optional

import assets
from models import LeagueSnapshot, MatchupInfo, PlayerInfo, TeamInfo

esc = html.escape


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------
def icon(name: str, cls: str = "") -> str:
    return f'<span class="ms {cls}" aria-hidden="true">{name}</span>'


def chip(text: str, kind: str = "", ic: Optional[str] = None) -> str:
    return f'<span class="chip {kind}{"" if ic else " plain"}">{icon(ic) if ic else ""}{esc(text)}</span>'


def section(title: str, aside: str = "") -> str:
    return f'<div class="sec"><h3>{esc(title)}</h3><span class="rule"></span>{f"<span class=aside>{aside}</span>" if aside else ""}</div>'


def notice(text: str, kind: str = "", ic: str = "info") -> str:
    return f'<div class="notice {kind}" role="status">{icon(ic)}<div>{text}</div></div>'


def empty(title: str, body: str = "", ic: str = "search_off") -> str:
    return f'<div class="empty glass-med">{icon(ic)}<b>{esc(title)}</b>{esc(body)}</div>'


def skeleton(n: int = 3, h: int = 64) -> str:
    return "".join(f'<div class="skel" style="height:{h}px;margin:8px 0" aria-hidden="true"></div>' for _ in range(n)) + \
           '<span class="sr-only" role="status">Loading</span>'


def fmt_pts(x: float) -> str:
    return f"{x:.1f}"


def signed(x: float) -> str:
    return f"{x:+.1f}"


def ago(seconds: Optional[float]) -> str:
    if seconds is None:
        return "just now"
    m = int(seconds // 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 60 else f"{m // 60} h ago"


def fresh(seconds: Optional[float], ttl: int) -> str:
    stale = seconds is not None and seconds > ttl * 2
    return (f'<span class="fresh {"stale" if stale else ""}">{icon("schedule")}'
            f'{"Stale - " if stale else ""}Updated {ago(seconds)}</span>')


# ---------------------------------------------------------------------------
# game time / lock state
# ---------------------------------------------------------------------------
def kickoff(p: PlayerInfo) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(p.game_time) if p.game_time else None
    except ValueError:
        return None


def kick_label(p: PlayerInfo) -> str:
    k = kickoff(p)
    if not k:
        return "Bye" if p.on_bye else ""
    return k.strftime("%a %-I:%M %p")


def lock_state(p: PlayerInfo, now: Optional[datetime] = None) -> str:
    """'bye' | 'locked' (game has started) | 'open' | ''."""
    if p.on_bye:
        return "bye"
    k = kickoff(p)
    if not k:
        return ""
    return "locked" if k <= (now or datetime.now()) else "open"


# ---------------------------------------------------------------------------
# brand-aware renderer
# ---------------------------------------------------------------------------
class Brand:
    """Resolves logos/headshots once per page render, verified server-side."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        self.ok: dict[str, bool] = {}

    def prefetch(self, players: Iterable[PlayerInfo] = (), teams: Iterable[TeamInfo] = (), widths=(120,)) -> None:
        urls = [assets.headshot_url(p.player_id, w) for p in players if p.position != "D/ST" for w in widths]
        urls += [assets.team_logo(p.pro_team, self.db_path) for p in players if p.position == "D/ST"]
        urls += [t.logo for t in teams if t.logo and not t.logo.endswith(".svg")]
        self.ok.update(assets.verified(urls, self.db_path))

    def _good(self, url: str) -> bool:
        if url not in self.ok:
            self.ok.update(assets.verified([url], self.db_path))
        return self.ok.get(url, False)

    # ---- NFL team ----
    def color(self, abbr: str) -> str:
        return assets.usable_color(assets.team(abbr, self.db_path).color)

    def logo(self, abbr: str, size: int = 22) -> str:
        t = assets.team(abbr, self.db_path)
        url = assets.team_logo(abbr, self.db_path)
        inner = (f'<img src="{esc(url)}" alt="" width="{size}" height="{size}" loading="lazy" decoding="async">'
                 if url and self._good(url) else f"<b>{esc(abbr[:3])}</b>")
        return f'<span class="logo" style="--s:{size}px" title="{esc(t.name)}">{inner}</span>'

    def nfl_tag(self, abbr: str) -> str:
        if not abbr or abbr == "None":
            return ""
        return f'<span style="display:inline-flex;align-items:center;gap:5px">{self.logo(abbr, 16)}{esc(abbr)}</span>'

    # ---- players ----
    def avatar(self, p: PlayerInfo, size: int = 44) -> str:
        tc = self.color(p.pro_team)
        if p.position == "D/ST":
            url = assets.team_logo(p.pro_team, self.db_path)
            inner = (f'<img src="{esc(url)}" alt="" loading="lazy" decoding="async">' if url and self._good(url) else f"<span>{esc(p.pro_team)}</span>")
            return f'<span class="avatar logo" style="--s:{size}px;--tc:{tc}">{inner}</span>'
        w = 120 if size <= 64 else 360
        url = assets.headshot_url(p.player_id, w)
        inner = (f'<span>{esc(assets.initials(p.name))}</span>'
                 + (f'<img src="{esc(url)}" alt="" width="{size}" height="{round(size * .73)}" loading="lazy" decoding="async">' if self._good(url) else ""))
        return f'<span class="avatar" style="--s:{size}px;--tc:{tc}">{inner}</span>'

    # distinct, muted identity colors for fantasy teams that have no custom logo (stable per team id)
    _FANTASY = ["#4f74e3", "#c2410c", "#0f766e", "#7c3aed", "#b45309", "#be185d", "#15803d", "#0369a1", "#a21caf", "#b91c1c", "#4d7c0f", "#475569"]

    def team_avatar(self, t: TeamInfo, size: int = 56) -> str:
        tc = self._FANTASY[(t.team_id - 1) % len(self._FANTASY)]
        if t.logo and not t.logo.endswith(".svg") and self._good(t.logo):
            return f'<span class="avatar logo" style="--s:{size}px;--tc:{tc}"><img src="{esc(t.logo)}" alt="" loading="lazy" decoding="async"></span>'
        return f'<span class="avatar" style="--s:{size}px;--tc:{tc}" title="{esc(t.name)}"><span>{esc(assets.initials(t.name))}</span></span>'

    # ---- chips ----
    def status_chip(self, p: PlayerInfo) -> str:
        if p.on_bye:
            return chip("Bye week", "info", "event_busy")
        s = p.injury_status
        if s == "ACTIVE":
            return ""
        label = s.replace("_", " ").title().replace("Injury Reserve", "IR")
        if p.is_out:
            return chip(label, "bad", "medical_services")
        if s == "DOUBTFUL":
            return chip(label, "bad", "warning")
        return chip(label, "warn", "help")

    # ---- rows ----
    def player_row(self, p: PlayerInfo, *, slot: str = "", moved: bool = False, show_actual: bool = True,
                   value_pct: Optional[float] = None, value_label: str = "", note: str = "") -> str:
        cls = " ".join(c for c in ("out" if (p.is_out or p.on_bye) else "risk" if p.is_risky else "", "moved" if moved else "") if c)
        opp = (f"vs {esc(p.opponent)}" if p.opponent else ("Bye" if p.on_bye else ""))
        kl = kick_label(p)
        lock = lock_state(p)
        lock_chip = chip("Locked", "", "lock") if lock == "locked" else ""
        proj = fmt_pts(p.week_proj) if not p.on_bye else "-"
        bar = (f'<div class="bar" aria-hidden="true"><i style="width:{max(2, min(100, value_pct)):.0f}%"></i></div>' if value_pct is not None else "")
        stat2 = (f'<div class="stat hide-sm"><b>{fmt_pts(p.week_points)}</b><small>Actual</small></div>' if show_actual else
                 f'<div class="stat hide-sm"><b>{esc(value_label or fmt_pts(p.actual_ppg))}</b><small>{"ROS value" if value_label else "Avg"}</small>{bar}</div>')
        return (
            f'<div class="row {cls}" role="listitem" style="--tc:{self.color(p.pro_team)}">'
            f'<div class="who">{f"<span class=slot>{esc(slot)}</span>" if slot else ""}{self.avatar(p, 44)}'
            f'<div style="min-width:0"><div class="nm">{esc(p.name)}</div>'
            f'<div class="sub">{chip(p.position, "pos")}{self.nfl_tag(p.pro_team)}{self.status_chip(p)}{lock_chip}{esc(note)}</div></div></div>'
            f'<div class="opp">{opp}<small>{esc(kl) if not p.on_bye else ""}</small></div>'
            f'<div class="stat"><b>{proj}</b><small>Proj</small></div>{stat2}</div>'
        )

    def rows(self, inner: str) -> str:
        return f'<div class="rows solid" role="list">{inner}</div>'

    # ---- scoreboard ----
    def scoreboard(self, a: TeamInfo, b: TeamInfo, a_score: float, b_score: float, a_proj: float, b_proj: float,
                   week: int, state: str, fresh_html: str = "") -> str:
        ca, cb = "#4f74e3", "#9aa3b2"
        edge = a_proj - b_proj
        fav = (f"{a.name} favored by {abs(edge):.1f} (projection)" if edge > 0.05 else
               f"{b.name} favored by {abs(edge):.1f} (projection)" if edge < -0.05 else "Projected dead even")
        started = state != "Pregame"
        side = lambda t, r: (f'<div class="side{" r" if r else ""}">{self.team_avatar(t, 64)}<div style="min-width:0">'
                             f'<div class="name">{esc(t.name)}</div><div class="sub">{esc(t.owner_label)} · {esc(t.record)} · #{t.standing}</div></div></div>')
        score = lambda proj, act: (f'<div class="p"><span class="legend">Projected</span><span class="big num">{proj:.1f}</span>'
                                   + (f'<div class="actual num">Actual {act:.1f}</div>' if started else "") + "</div>")
        return (
            f'<section class="board glass" style="--tc-a:{ca};--tc-b:{cb}" aria-label="Week {week} matchup">'
            f'<div class="meta"><span>Week {week} · {esc(state)}</span><span>{fresh_html}</span></div>'
            f'<div class="grid">{side(a, False)}<div class="score"><div class="pair">{score(a_proj, a_score)}<span class="sep">–</span>{score(b_proj, b_score)}</div></div>{side(b, True)}</div>'
            f'<div class="foot">{chip(fav, "info", "insights")}{chip("ESPN projections, not a win-probability model", "", "info")}</div></section>'
        )

    # ---- recommendation card ----
    def rec_card(self, title: str, body: str, *, ic: str = "bolt", tone: str = "", gain: Optional[float] = None,
                 gain_label: str = "pts", why: str = "", todo: str = "", players: Iterable[PlayerInfo] = ()) -> str:
        av = "".join(f'<span style="margin-left:-8px">{self.avatar(p, 34)}</span>' for p in list(players)[:3])
        g = f'<div class="gain"><b>{signed(gain)}</b><small>{esc(gain_label)}</small></div>' if gain is not None else ""
        why_html = f'<div class="why">{esc(why)}</div>' if why else ""
        todo_html = f'<div class="todo">{icon("arrow_forward")}<span>{esc(todo)}</span></div>' if todo else ""
        faces = f'<div style="display:flex">{av}</div>' if av else ""
        return (f'<article class="rec glass-med"><div class="ic {tone}">{icon(ic)}</div><div style="min-width:0;flex:1">'
                f'<h4>{esc(title)}</h4><p>{body}</p>{why_html}{todo_html}</div>{faces}{g}</article>')


# ---------------------------------------------------------------------------
# trend chart (inline SVG with a table alternative)
# ---------------------------------------------------------------------------
def trend_chart(history: list[dict], *, color: str = "#4f74e3", current_season: int = 0, week_proj: float = 0.0,
                current_week: int = 0, scoring_note: str = "") -> str:
    """Bar chart (plain HTML/CSS, since Streamlit strips inline SVG) of weekly fantasy points under THIS league's scoring.
    `history`: [{season, week, points, source}] oldest -> newest."""
    if not history:
        return empty("No game history yet", "ESPN hasn't posted weekly scores for this player.", "show_chart")
    pts = [h["points"] for h in history]
    ymax = max(pts + [week_proj, 10])
    step = 10 if ymax <= 40 else 20
    top = (int(ymax // step) + 1) * step
    pct = lambda v: max(0.0, min(100.0, 100.0 * v / top))
    cur = [h for h in history if h["season"] == current_season]
    avg = sum(h["points"] for h in cur) / len(cur) if cur else 0.0
    summary = (f"Weekly fantasy points, {len(history)} games, latest {history[-1]['points']:.1f}"
               + (f", {current_season} average {avg:.1f}" if cur else ""))
    grid = "".join(f'<i class="gl" style="bottom:{pct(g):.1f}%"><b class="num">{g}</b></i>' for g in range(0, top + 1, step))
    cols, labels, prev = [], [], None
    for h in history:
        is_cur = h["season"] == current_season
        tag = " (computed from your scoring rules)" if h.get("source") == "computed" else ""
        cols.append(f'<div class="col" title="{h["season"]} week {h["week"]}: {h["points"]:.1f} pts{tag}">'
                    f'<span class="bar{" cur" if is_cur else ""}" style="height:{pct(h["points"]):.1f}%"></span></div>')
        season_tag = f'<em>{h["season"]}</em>' if h["season"] != prev else ""
        prev = h["season"]
        labels.append(f'<div class="xl num">{season_tag}{h["week"] if h["week"] % 2 == 0 or h is history[-1] else "&nbsp;"}</div>')
    if week_proj and current_week:
        cols.append(f'<div class="col" title="Week {current_week} ESPN projection: {week_proj:.1f}"><span class="bar proj" style="height:{pct(week_proj):.1f}%"></span></div>')
        labels.append(f'<div class="xl num"><em style="color:{color}">proj</em>{current_week}</div>')
    avg_line = (f'<i class="avg" style="bottom:{pct(avg):.1f}%"><b class="num">{current_season} avg {avg:.1f}</b></i>' if cur else "")
    rows = "".join(f'<tr><td>{h["season"]} wk {h["week"]}</td><td>{h["points"]:.1f}</td></tr>' for h in history)
    note = f' under your scoring ({esc(scoring_note)})' if scoring_note else " under your league scoring"
    return (f'<div class="tc" style="--tc:{color}" role="img" aria-label="{esc(summary)}"><div class="plot">{grid}{avg_line}<div class="cols">{"".join(cols)}</div></div>'
            f'<div class="xrow">{"".join(labels)}</div></div>'
            f'<div class="fresh" style="margin-top:8px">{icon("rule")}Fantasy points{note}. Dashed bar = this week\'s ESPN projection.</div>'
            f'<details style="margin-top:6px"><summary class="fresh" style="cursor:pointer">View as table</summary>'
            f'<table class="cmp" style="max-width:260px;margin-top:6px"><tr><th>Game</th><th>Pts</th></tr>{rows}</table></details>')
