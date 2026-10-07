"""Per-player news/injury feed (ESPN player news + Sleeper injury data) and lineup-impact alerts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import db
from models import LeagueSnapshot, PlayerInfo, TeamInfo
from optimizer import plan_lineup
from sleeper import SleeperIndex

NEWS_TTL = 900
RECENT_HOURS = 72
# Phrases in news text that usually mean "don't start this guy" / "watch this guy".
BAD_PHRASES = ["ruled out", "will not play", "won't play", "inactive", "did not practice", "expected to miss",
               "placed on injured reserve", "injured reserve", "underwent surgery", "suspended", "doubtful",
               "unlikely to play", "game-time decision", "limited in practice", "left the game", "exited the game"]
GOOD_PHRASES = ["full participant", "cleared", "expected to play", "returns to practice", "activated", "will start"]

ACT, WATCH, INFO = "ACT", "WATCH", "INFO"
_SEV_ORDER = {ACT: 0, WATCH: 1, INFO: 2}


@dataclass
class NewsItem:
    headline: str
    story: str = ""
    published: str = ""
    source: str = "ESPN"

    def age_hours(self, now: Optional[datetime] = None) -> Optional[float]:
        try:
            t = datetime.fromisoformat(self.published.replace("Z", "+00:00"))
        except ValueError:
            return None
        return ((now or datetime.now(timezone.utc)) - t).total_seconds() / 3600

    def text(self) -> str:
        return f"{self.headline} {self.story}".lower()


@dataclass
class PlayerNews:
    player: PlayerInfo
    items: list[NewsItem] = field(default_factory=list)
    sleeper: dict = field(default_factory=dict)       # injury_status / body part / notes / status

    @property
    def injury_line(self) -> str:
        sl = self.sleeper
        parts = [x for x in (sl.get("injury_status"), sl.get("injury_body_part")) if x]
        return " - ".join(parts)


@dataclass
class Alert:
    player: PlayerInfo
    severity: str
    message: str
    action: str = ""
    owner: str = ""        # team name the player belongs to


def get_player_news(player: PlayerInfo, fetch: Callable[[int, int], list[dict]], index: Optional[SleeperIndex] = None,
                    limit: int = 5, db_path: Optional[str] = None) -> PlayerNews:
    key = f"news:{player.player_id}"
    raw = db.cache_get(key, NEWS_TTL, db_path)
    if raw is None:
        try:
            raw = fetch(player.player_id, limit)
        except Exception:
            raw = []
        db.cache_set(key, raw, db_path)
    items = [NewsItem(r.get("headline", ""), r.get("story", ""), r.get("published", ""), r.get("source", "ESPN")) for r in raw[:limit]]
    return PlayerNews(player, items, index.injury(player) if index else {})


def _sentences_about(it: NewsItem, player: PlayerInfo) -> list[str]:
    """Sentences of this item that actually mention the player (guards against roundup articles)."""
    last = player.name.lower().split()[-1].rstrip(".") if player.position != "D/ST" else player.name.lower().split()[0]
    text = f"{it.headline}. {it.story}".lower()
    return [x for x in re.split(r"(?<=[.!?])\s+", text) if last in x]


def _flags(pn: PlayerNews, now: Optional[datetime] = None) -> tuple[list[str], list[str]]:
    bad, good = [], []
    for it in pn.items:
        age = it.age_hours(now)
        if age is None or age > RECENT_HOURS:
            continue
        for sentence in _sentences_about(it, pn.player):
            bad += [ph for ph in BAD_PHRASES if ph in sentence]
            good += [ph for ph in GOOD_PHRASES if ph in sentence]
    return bad, good


def lineup_alerts(snap: LeagueSnapshot, team: TeamInfo, news: dict[int, PlayerNews],
                  now: Optional[datetime] = None) -> list[Alert]:
    """Things about `team`'s roster that should change (or might change) this week's lineup."""
    plan = plan_lineup(team.roster, snap.starter_slots)
    replacements = {s.player_out.player_id: s for s in plan.swaps if s.player_out}
    starters = {p.player_id for _, p in plan.current if p}
    optimal = {p.player_id for _, p in plan.optimal if p}
    alerts: list[Alert] = []

    def add(p, sev, msg, action=""):
        alerts.append(Alert(p, sev, msg, action, team.name))

    for p in team.roster:
        pn = news.get(p.player_id) or PlayerNews(p)
        is_starting = p.player_id in starters
        relevant = is_starting or p.player_id in optimal
        sl_status = (pn.sleeper.get("injury_status") or "").upper()
        swap = replacements.get(p.player_id)
        fix = swap.action() if swap else ""

        if p.on_bye and is_starting:
            add(p, ACT, f"{p.name} is on a bye but in your starting lineup.", fix)
        elif p.is_out and is_starting:
            add(p, ACT, f"{p.name} is {p.injury_status.replace('_', ' ').title()} but in your starting lineup.", fix)
        elif p.injury_status == "DOUBTFUL" and is_starting:
            add(p, ACT, f"{p.name} is Doubtful - unlikely to play.", fix)
        elif sl_status in ("OUT", "IR", "DOUBTFUL") and p.injury_status == "ACTIVE" and relevant:
            add(p, ACT, f"Sleeper lists {p.name} as {sl_status.title()} ({pn.injury_line}) but ESPN still shows Active - ESPN may be behind.", fix)
        elif p.injury_status == "QUESTIONABLE" and relevant:
            add(p, WATCH, f"{p.name} is Questionable{(' (' + pn.sleeper['injury_body_part'] + ')') if pn.sleeper.get('injury_body_part') else ''}. Check status before kickoff.")

        bad, good = _flags(pn, now)
        if bad and relevant and not any(a.player is p and a.severity == ACT for a in alerts):
            about = next(it for it in pn.items if any(bad[0] in x for x in _sentences_about(it, p)))
            add(p, WATCH, f"Recent news on {p.name} mentions '{bad[0]}': {about.headline[:140]}")
        elif good and p.injury_status in ("QUESTIONABLE", "DOUBTFUL"):
            add(p, INFO, f"Positive sign for {p.name}: news mentions '{good[0]}'.")
    alerts.sort(key=lambda a: _SEV_ORDER[a.severity])
    return alerts


def collect_team_news(team: TeamInfo, fetch, index: Optional[SleeperIndex] = None,
                      db_path: Optional[str] = None) -> dict[int, PlayerNews]:
    return {p.player_id: get_player_news(p, fetch, index, db_path=db_path) for p in team.roster}
