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
# edge engine: adjusted projections with an expandable "why"
# ---------------------------------------------------------------------------
EDGE_LABEL = {"cascade": "Injury cascade", "defense": "Opposing defense / OL injuries", "vegas": "Game environment (Vegas)", "weather": "Weather",
              "regression": "Opportunity vs. production", "schedule": "Rest-of-season schedule", "news": "News"}
TAG_ICON = {"buy low": "trending_up", "sell high": "trending_down", "role growing": "moving"}


def edge_label(p: PlayerInfo) -> str:
    """'ESPN 12.4 → Adjusted 14.9' (or just the ESPN number when nothing was adjusted)."""
    if p.has_edge:
        return f"ESPN {p.espn_week_proj:.1f} → Adjusted {p.week_proj:.1f}"
    return f"ESPN {p.week_proj:.1f}"


def _clock(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%a %-I:%M %p") if ts else ""


def edge_why(p: PlayerInfo, open_: bool = False) -> str:
    """Expandable list of every adjustment: size, plain-English reason, source, confidence, timestamp."""
    if not p.has_edge:
        return ""
    items = "".join(
        f'<li><b class="num {"up" if a["delta"] > 0 else "dn"}">{a["delta"]:+.1f}</b> <span class="et">{esc(EDGE_LABEL.get(a["type"], a["type"]))}</span>'
        f'<div>{esc(a["reason"])}</div><small>Source: {esc(a["source"])} · {esc(a["confidence"])} confidence · {esc(_clock(a["at"]))}'
        f'{" · capped from " + format(a["raw"], "+.1f") if abs(a.get("raw", a["delta"]) - a["delta"]) >= 0.05 else ""}</small></li>' for a in sorted(p.edge, key=lambda a: -abs(a["delta"])))
    return (f'<details class="why"{" open" if open_ else ""}><summary>{icon("bolt")}{esc(edge_label(p))}<span class="chev">why</span></summary>'
            f'<ul>{items}</ul><div class="fine">Adjustments are added to ESPN\'s projection and capped per player. Missing data means no adjustment.</div></details>')


def edge_context(p: PlayerInfo, open_: bool = False) -> str:
    """Informational notes (e.g. an injury cascade) that are deliberately NOT part of the projection."""
    if not p.context:
        return ""
    items = "".join(f'<li><b class="num {"up" if c["pts"] > 0 else "dn"}">{c["pts"]:+.1f}</b> <span class="et">{esc(EDGE_LABEL.get(c["kind"], c["kind"]))} (context)</span>'
                    f'<div>{esc(c["text"])}</div><small>Source: {esc(c.get("source", ""))} · {esc(c.get("confidence", "low"))} confidence</small></li>' for c in p.context)
    return (f'<details class="why ctx"{" open" if open_ else ""}><summary>{icon("info")}Opportunity context<span class="chev">not in projection</span></summary><ul>{items}</ul>'
            f'<div class="fine">Shown for information. In the backtest this estimate did not improve weekly accuracy over a player\'s recent form, so it does not move the projection.</div></details>')


def tag_chips(p: PlayerInfo) -> str:
    return "".join(f'<span class="chip tag" title="{esc(t[1])}">{icon(TAG_ICON.get(t[0], "sell"))}{esc(t[0])}</span>' for t in p.tags)


def game_env_html(env, compact: bool = False) -> str:
    """Vegas + weather for one team's game, with the forecast timestamp."""
    if env is None:
        return notice("No game-environment data for this team this week.", "", "sports_football")
    fav = "" if env.spread is None else (f"{env.team} favored by {env.spread:.1f}" if env.spread > 0 else f"{env.opp} favored by {-env.spread:.1f}" if env.spread < 0 else "Pick'em")
    vegas = (f'{chip(fav, "", "attach_money")}{chip(f"Total {env.total:.1f}", "", "functions")}{chip(f"{env.team} implied {env.implied:.1f}", "", "scoreboard")}'
             if env.spread is not None else chip("No Vegas line available", "", "attach_money"))
    if env.wind_mph is not None:
        w = chip(f"Wind {env.wind_mph:.0f} mph", "warn" if env.wind_mph >= 15 else "", "air") + chip(f"{env.temp_f:.0f}°F", "warn" if env.temp_f <= 25 else "", "thermostat")
        if env.precip_prob:
            w += chip(f"{env.precip_prob:.0f}% precip", "", "rainy")
    else:
        w = chip(env.weather_note or "Weather n/a", "", "partly_cloudy_day")
    stamp = f'<small class="fresh">Lines: {esc(env.lines_source)}' + (f" · forecast {esc(_clock(env.forecast_at))}" if env.forecast_at and env.wind_mph is not None else "") + "</small>"
    return f'<div class="fh-ctx">{vegas}{w}</div>{stamp}'


def news_event_html(ev: dict, link: bool = True) -> str:
    """One AI-parsed news item, clearly labeled as extracted (not written) by AI, with the raw text and a source link."""
    st_map = {"out": ("Out", "bad"), "ir": ("IR", "bad"), "suspended": ("Suspended", "bad"), "doubtful": ("Doubtful", "bad"), "questionable": ("Questionable", "warn"), "active": ("Cleared", "good")}
    st = st_map.get(ev.get("status") or "", None)
    chips = chip("AI-extracted from ESPN news", "ai", "auto_awesome") + (chip(st[0], st[1], "medical_services") if st else chip(ev.get("event_type", "news").replace("_", " ").title(), "", "newspaper"))
    if ev.get("expected_games_missed"):
        chips += chip(f"{ev['expected_games_missed']} games", "", "event_busy")
    src = f' <a href="{esc(ev["source_url"])}" target="_blank" rel="noopener">source</a>' if link and ev.get("source_url") else ""
    ben = f'<div class="fresh">Named as picking up work: {esc(", ".join(ev["beneficiaries"]))}</div>' if ev.get("beneficiaries") else ""
    return (f'<div class="news"><div class="fh-ctx">{chips}<b>{esc(ev.get("player", ""))}</b></div><p>{esc(ev.get("summary", ""))}</p>{ben}'
            f'<details><summary class="fresh">Original text</summary><p>{esc(ev.get("raw_text", "")[:700])}</p></details>'
            f'<small>{esc(str(ev.get("published_at", ""))[:16].replace("T", " "))} UTC{src}</small></div>')


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

    def __init__(self, db_path: Optional[str] = None, cookies: Optional[dict] = None):
        self.db_path = db_path
        self.cookies = cookies                      # ESPN league cookies, used server-side only (never put into markup)
        self._flogo: dict[str, Optional[str]] = {}
        self.watch: set[int] = set()                # ESPN ids on the user's watchlist
        self.ok: dict[str, bool] = {}
        self._geo: Optional[dict] = None

    def prefetch(self, players: Iterable[PlayerInfo] = (), teams: Iterable[TeamInfo] = (), widths=(120,)) -> None:
        urls = [assets.headshot_url(p.player_id, w) for p in players if p.position != "D/ST" for w in widths]
        urls += [assets.team_logo(p.pro_team, self.db_path) for p in players if p.position == "D/ST"]
        self.ok.update(assets.verified(urls, self.db_path))

    def _good(self, url: str) -> bool:
        if url not in self.ok:
            self.ok.update(assets.verified([url], self.db_path))
        return self.ok.get(url, False)

    # ---- NFL team ----
    def color(self, abbr: str) -> str:
        return assets.usable_color(assets.team(abbr, self.db_path).color)

    def team_badge(self, abbr: str, size: int = 22, ring: bool = True) -> str:
        """The one NFL team badge used everywhere (rows, cards, headers, chips).
        Fixed box (no layout shift), ring drawn as the badge's own border at one thickness for every size, artwork centered
        and sized from its measured visible bounds, and a neutral abbreviation fallback if the logo can't load."""
        t = assets.team(abbr, self.db_path)
        url = assets.team_logo(abbr, self.db_path)
        ring_css = f"--tc:{self.color(abbr)};" if ring else "--tc:transparent;"
        label = esc(t.name if t.abbr != "NFL" else (abbr or "NFL"))
        if url and self._good(url):
            if self._geo is None:
                self._geo = assets.logo_geometry(self.db_path)
            dx, dy, k = assets.logo_transform(self._geo.get(t.abbr))
            inner = (f'<img src="{esc(url)}" alt="" width="{size}" height="{size}" loading="lazy" decoding="async" '
                     f'style="--dx:{dx}%;--dy:{dy}%;--k:{k}">')
            cls = "tbadge"
        else:
            inner = f"<b>{esc((abbr or '?')[:3])}</b>"
            cls = "tbadge fb"
        return f'<span class="{cls}" style="--s:{size}px;{ring_css}" role="img" aria-label="{label}" title="{label}">{inner}</span>'

    logo = team_badge          # backwards-compatible name

    def team_banner(self, abbr: str) -> str:
        """NFL team identity strip for profile headers: big badge, official name, localized team color."""
        t = assets.team(abbr, self.db_path)
        return (f'<div class="tbanner" style="--tc:{self.color(abbr)}">{self.team_badge(abbr, 46)}<div><b>{esc(t.name)}</b>'
                f'<small>{esc(t.abbr)}</small></div></div>')

    def nfl_tag(self, abbr: str) -> str:
        if not abbr or abbr == "None":
            return ""
        return f'<span style="display:inline-flex;align-items:center;gap:5px">{self.team_badge(abbr, 18)}{esc(abbr)}</span>'

    # ---- players ----
    def avatar(self, p: PlayerInfo, size: int = 44) -> str:
        tc = self.color(p.pro_team)
        if p.position == "D/ST":
            return self.team_badge(p.pro_team, size)
        w = 120 if size <= 64 else 360
        url = assets.headshot_url(p.player_id, w)
        inner = (f'<span>{esc(assets.initials(p.name))}</span>'
                 + (f'<img src="{esc(url)}" alt="" width="{size}" height="{round(size * .73)}" loading="lazy" decoding="async">' if self._good(url) else ""))
        return f'<span class="avatar" style="--s:{size}px;--tc:{tc}">{inner}</span>'

    # distinct, muted identity colors for fantasy teams that have no custom logo (stable per team id)
    _FANTASY = ["#4f74e3", "#c2410c", "#0f766e", "#7c3aed", "#b45309", "#be185d", "#15803d", "#0369a1", "#a21caf", "#b91c1c", "#4d7c0f", "#475569"]

    def team_avatar(self, t: TeamInfo, size: int = 56) -> str:
        """A fantasy team's own logo (custom upload or ESPN default), falling back to initials on a per-team identity color."""
        tc = self._FANTASY[(t.team_id - 1) % len(self._FANTASY)]
        if t.logo not in self._flogo:
            self._flogo[t.logo] = assets.fantasy_logo_src(t.logo, self.cookies, self.db_path)
        src = self._flogo[t.logo]
        label = esc(t.name)
        if src:
            cls = "avatar flogo" if src.startswith("data:") else "avatar dflogo"      # ESPN default glyphs sit on the team's identity color
            return (f'<span class="{cls}" style="--s:{size}px;--tc:{tc}" role="img" aria-label="{label}" title="{label}">'
                    f'<img src="{src}" alt="" width="{size}" height="{size}" loading="lazy" decoding="async"></span>')
        return f'<span class="avatar" style="--s:{size}px;--tc:{tc}" role="img" aria-label="{label}" title="{label}"><span>{esc(assets.initials(t.name))}</span></span>'

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
        edge_chip = chip(f"Edge {p.edge_total:+.1f}", "ai", "bolt") if p.has_edge and not p.on_bye else ""
        proj_label = (f'<small title="{esc(edge_label(p))}">ESPN {p.espn_week_proj:.1f}</small>' if p.has_edge and not p.on_bye else "<small>Proj</small>")
        bar = (f'<div class="bar" aria-hidden="true"><i style="width:{max(2, min(100, value_pct)):.0f}%"></i></div>' if value_pct is not None else "")
        stat2 = (f'<div class="stat hide-sm"><b>{fmt_pts(p.week_points)}</b><small>Actual</small></div>' if show_actual else
                 f'<div class="stat hide-sm"><b>{esc(value_label or fmt_pts(p.actual_ppg))}</b><small>{"ROS value" if value_label else "Avg"}</small>{bar}</div>')
        return (
            f'<div class="row {cls}" role="listitem" style="--tc:{self.color(p.pro_team)}">'
            f'<div class="who">{f"<span class=slot>{esc(slot)}</span>" if slot else ""}{self.avatar(p, 44)}'
            f'<div style="min-width:0"><div class="nm">{esc(p.name)}</div>'
            f'<div class="sub">{chip(p.position, "pos")}{self.nfl_tag(p.pro_team)}{self.status_chip(p)}{lock_chip}{edge_chip}{tag_chips(p)}{chip('Watching', '', 'star') if p.player_id in self.watch else ''}{esc(note)}</div>{edge_why(p)}{edge_context(p)}</div></div>'
            f'<div class="opp">{opp}<small>{esc(kl) if not p.on_bye else ""}</small></div>'
            f'<div class="stat{" edge" if p.has_edge and not p.on_bye else ""}"><b>{proj}</b>{proj_label}</div>{stat2}</div>'
        )

    def rows(self, inner: str) -> str:
        return f'<div class="rows solid" role="list">{inner}</div>'

    # ---- scoreboard ----
    def scoreboard(self, a: TeamInfo, b: TeamInfo, a_score: float, b_score: float, a_proj: float, b_proj: float,
                   week: int, state: str, fresh_html: str = "") -> str:
        edge = a_proj - b_proj
        fav = (f"{a.name} favored by {abs(edge):.1f} (projection)" if edge > 0.05 else
               f"{b.name} favored by {abs(edge):.1f} (projection)" if edge < -0.05 else "Projected dead even")
        started = state != "Pregame"
        side = lambda t, r: (f'<div class="side{" r" if r else ""}">{self.team_avatar(t, 64)}<div style="min-width:0">'
                             f'<div class="name">{esc(t.name)}</div><div class="sub">{esc(t.owner_label)} · {esc(t.record)} · #{t.standing}</div></div></div>')
        score = lambda proj, act: (f'<div class="p"><span class="legend">Projected</span><span class="big num">{proj:.1f}</span>'
                                   + (f'<div class="actual num">Actual {act:.1f}</div>' if started else "") + "</div>")
        return (
            f'<section class="board glass silver" aria-label="Week {week} matchup">'
            f'<div class="meta"><span>Week {week} · {esc(state)}</span><span>{fresh_html}</span></div>'
            f'<div class="grid">{side(a, False)}<div class="score"><div class="pair">{score(a_proj, a_score)}<span class="sep">–</span>{score(b_proj, b_score)}</div></div>{side(b, True)}</div>'
            f'<div class="foot">{chip(fav, "info", "insights")}{chip("ESPN projections, not a win-probability model", "", "info")}</div></section>'
        )

    # ---- recommendation card ----
    def rec_card(self, title: str, body: str, *, ic: str = "bolt", tone: str = "", gain: Optional[float] = None,
                 gain_label: str = "pts", why: str = "", todo: str = "", players: Iterable[PlayerInfo] = (), feature: bool = False, edge_note: str = "") -> str:
        av = "".join(f'<span style="margin-left:-8px">{self.avatar(p, 34)}</span>' for p in list(players)[:3])
        g = f'<div class="gain"><b>{signed(gain)}</b><small>{esc(gain_label)}</small></div>' if gain is not None else ""
        why_html = f'<div class="why">{esc(why)}</div>' if why else ""
        todo_html = f'<div class="todo">{icon("arrow_forward")}<span>{esc(todo)}</span></div>' if todo else ""
        edge_html = f'<div class="edgenote">{icon("bolt")}<span>{esc(edge_note)}</span></div>' if edge_note else ""
        faces = f'<div style="display:flex">{av}</div>' if av else ""
        return (f'<article class="rec glass-med{" feature" if feature else ""}"><div class="ic {tone}">{icon(ic)}</div><div style="min-width:0;flex:1">'
                f'<h4>{esc(title)}</h4><p>{body}</p>{why_html}{edge_html}{todo_html}</div>{faces}{g}</article>')


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
