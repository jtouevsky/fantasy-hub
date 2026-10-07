"""The ONLY module that touches `espn-api`. Everything else consumes `models.*`.

Read-only by design: this wrapper never calls anything that changes a roster.
"""
from __future__ import annotations

import time
from typing import Optional

from espn_api.football import League
from espn_api.football.constant import POSITION_MAP, PRO_TEAM_MAP
from espn_api.requests.espn_requests import ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError

import db
from config import Config
from models import LeagueSnapshot, MatchupInfo, Owner, PlayerInfo, TeamInfo


class LeagueConnectionError(RuntimeError):
    """Friendly, secret-free error for the UI."""


# ESPN calls the RB/WR/TE slot "RB/WR/TE"; everyone else calls it FLEX.
def _slot(name: str) -> str:
    return "FLEX" if name == "RB/WR/TE" else name


_SLOT_ORDER = ["QB", "RB", "WR", "TE", "RB/WR", "WR/TE", "FLEX", "OP", "D/ST", "K"]
_NON_STARTER = {"BE", "IR"}
_REAL_POSITIONS = {"QB", "RB", "WR", "TE", "K", "D/ST"}
REC_STAT_ID = 53
PASS_TD_STAT_ID = 4


def _norm_status(raw: Optional[str]) -> str:
    s = (raw or "ACTIVE").upper().replace(" ", "_")
    return "ACTIVE" if s in ("NORMAL", "") else s


def _player_to_info(p, owner_team_id: Optional[int], bye_by_team: dict[str, int]) -> PlayerInfo:
    """Convert an espn-api Player/BoxPlayer into PlayerInfo (season stats only)."""
    season = p.stats.get(0, {}) if hasattr(p, "stats") else {}
    total = float(season.get("points", 0) or 0)
    avg = float(season.get("avg_points", 0) or 0)
    games = int(round(total / avg)) if avg else 0
    pos = p.position or ""
    return PlayerInfo(
        player_id=int(p.playerId),
        name=p.name,
        position=pos,
        pro_team=p.proTeam,
        injury_status=_norm_status(p.injuryStatus),
        lineup_slot=_slot(getattr(p, "lineupSlot", "") or "BE") or "BE",
        eligible_slots=[_slot(s) for s in p.eligibleSlots],
        total_points=total,
        games_played=games,
        season_proj_ppg=float(season.get("projected_avg_points", 0) or 0),
        percent_owned=float(getattr(p, "percent_owned", -1) or -1),
        bye_week=bye_by_team.get(p.proTeam, 0),
        owner_team_id=owner_team_id,
        weekly_points={str(w): float(v["points"]) for w, v in p.stats.items()
                       if isinstance(w, int) and w > 0 and v.get("points") is not None and v.get("breakdown")},
    )


def _overlay_week(info: PlayerInfo, box) -> None:
    """Add this-week data from a BoxPlayer (projection, actual, bye, opponent, slot)."""
    info.week_proj = float(box.projected_points or 0)
    info.week_points = float(box.points or 0)
    info.on_bye = bool(box.on_bye_week)
    info.opponent = "" if box.pro_opponent == "None" else box.pro_opponent
    info.lineup_slot = _slot(box.slot_position) or info.lineup_slot
    info.injury_status = _norm_status(box.injuryStatus)
    gd = getattr(box, "game_date", None)
    info.game_time = gd.isoformat(timespec="minutes") if gd and not box.on_bye_week else ""


class LeagueClient:
    def __init__(self, cfg: Config):
        missing = cfg.missing_espn()
        if missing:
            raise LeagueConnectionError(f"Missing in .env: {', '.join(missing)}")
        self.cfg = cfg
        self._league: Optional[League] = None
        self._bye_map: dict[str, int] = {}
        self.last_warning: str = ""

    # ---- connection ------------------------------------------------------
    def _connect(self) -> League:
        if self._league is not None:
            return self._league
        try:
            self._league = League(
                league_id=self.cfg.league_id, year=self.cfg.year,
                espn_s2=self.cfg.espn_s2, swid=self.cfg.swid,
            )
        except ESPNAccessDenied:
            raise LeagueConnectionError(
                "ESPN denied access. Your ESPN_S2 / SWID cookies are missing, wrong, or expired - re-copy them (see README)."
            ) from None
        except ESPNInvalidLeague:
            raise LeagueConnectionError(f"League {self.cfg.league_id} not found for {self.cfg.year}. Check LEAGUE_ID and YEAR.") from None
        except ESPNUnknownError as e:
            raise LeagueConnectionError(f"ESPN returned an error: {e}") from None
        return self._league

    def _bye_weeks(self, league: League) -> dict[str, int]:
        """pro team abbrev -> NFL bye week, derived from the pro schedule."""
        if self._bye_map:
            return self._bye_map
        data = league.espn_request.get_pro_schedule()
        teams = data.get("settings", {}).get("proTeams", [])
        weeks_all: set[int] = set()
        by_team: dict[int, set[int]] = {}
        for t in teams:
            games = {int(k) for k, v in (t.get("proGamesByScoringPeriod") or {}).items() if v}
            if t["id"] != 0 and games:
                by_team[t["id"]] = games
                weeks_all |= games
        last = max(weeks_all) if weeks_all else 0
        for tid, games in by_team.items():
            missing = [w for w in range(1, last + 1) if w not in games]
            if missing and tid in PRO_TEAM_MAP:
                self._bye_map[PRO_TEAM_MAP[tid]] = missing[0]
        return self._bye_map

    # ---- league structure --------------------------------------------------
    def _lineup_slots(self, league: League) -> tuple[dict[str, int], int, int]:
        """Read starter/bench/IR slot counts straight from ESPN's raw settings."""
        raw = league.espn_request.league_get(params={"view": "mSettings"})
        counts = raw["settings"]["rosterSettings"]["lineupSlotCounts"]
        starters: dict[str, int] = {}
        bench = ir = 0
        for slot_id, n in counts.items():
            n = int(n)
            name = _slot(POSITION_MAP.get(int(slot_id), str(slot_id)))
            if n <= 0:
                continue
            if name == "BE":
                bench = n
            elif name == "IR":
                ir = n
            elif name not in _NON_STARTER:
                starters[name] = n
        ordered = {k: starters[k] for k in _SLOT_ORDER if k in starters}
        ordered.update({k: v for k, v in starters.items() if k not in ordered})
        return ordered, bench, ir

    @staticmethod
    def _scoring_notes(league: League) -> dict[str, float]:
        notes: dict[str, float] = {}
        for item in league.settings.scoring_format:
            if item.get("id") == REC_STAT_ID:
                notes["points_per_reception"] = float(item.get("points", 0))
            elif item.get("id") == PASS_TD_STAT_ID:
                notes["points_per_pass_td"] = float(item.get("points", 0))
        return notes

    # ---- snapshot ----------------------------------------------------------
    def fetch_snapshot(self) -> LeagueSnapshot:
        # espn-api's League.refresh() drops the football Settings class, so reconnect instead.
        self._league = None
        league = self._connect()
        self.last_warning = ""
        byes = self._bye_weeks(league)
        starters, bench, ir = self._lineup_slots(league)

        teams: list[TeamInfo] = []
        for t in league.teams:
            owners = [
                Owner(o.get("firstName", "").strip(), o.get("lastName", "").strip(), o.get("displayName", ""))
                for o in (t.owners or [])
            ]
            teams.append(TeamInfo(
                team_id=t.team_id, name=t.team_name, abbrev=t.team_abbrev, owners=owners,
                wins=t.wins, losses=t.losses, ties=t.ties,
                points_for=float(t.points_for), points_against=float(t.points_against),
                standing=int(t.standing or 0), playoff_pct=float(t.playoff_pct or 0),
                waiver_rank=int(t.waiver_rank or 0), logo=t.logo_url or "",
                faab_spent=float(getattr(t, "acquisition_budget_spent", 0) or 0),
                roster=[_player_to_info(p, t.team_id, byes) for p in t.roster],
            ))
        by_id = {t.team_id: t for t in teams}

        # Overlay this week's projections/actuals from the box scores.
        matchups: list[MatchupInfo] = []
        try:
            for bs in league.box_scores():
                for side in ("home", "away"):
                    team = getattr(bs, f"{side}_team")
                    lineup = getattr(bs, f"{side}_lineup")
                    tid = getattr(team, "team_id", None)
                    if tid in by_id:
                        roster = {p.player_id: p for p in by_id[tid].roster}
                        for bp in lineup:
                            if bp.playerId in roster:
                                _overlay_week(roster[bp.playerId], bp)
                home = getattr(bs.home_team, "team_id", None)
                away = getattr(bs.away_team, "team_id", None)
                matchups.append(MatchupInfo(
                    week=league.current_week, home_team_id=home, away_team_id=away,
                    home_score=float(bs.home_score), away_score=float(bs.away_score),
                    home_proj=float(bs.home_projected), away_proj=float(bs.away_projected),
                ))
        except Exception as e:  # preseason / ESPN hiccup: still show roster data
            self.last_warning = f"Weekly projections unavailable ({type(e).__name__}); showing season data only."


        return LeagueSnapshot(
            league_name=league.settings.name, year=league.year, week=league.current_week,
            final_week=int(league.finalScoringPeriod), reg_season_weeks=int(league.settings.reg_season_count),
            team_count=int(league.settings.team_count), my_team_id=self.cfg.team_id,
            starter_slots=starters, bench_slots=bench, ir_slots=ir,
            scoring_notes=self._scoring_notes(league), teams=teams, matchups=matchups,
            faab_budget=int(league.settings.acquisition_budget or 0) if league.settings.faab else 0,
            waiver_days=list(league.settings.waiver_process_days or []),
            fetched_at=time.time(),
        )

    def fetch_free_agents(self, position: Optional[str] = None, size: int = 50) -> list[PlayerInfo]:
        league = self._connect()
        byes = self._bye_weeks(league)
        out = []
        for bp in league.free_agents(size=size, position=position):
            info = _player_to_info(bp, None, byes)
            _overlay_week(info, bp)
            info.lineup_slot = "FA"
            if info.position in _REAL_POSITIONS:
                out.append(info)
        return out

    def fetch_player_news(self, espn_player_id: int, limit: int = 5) -> list[dict]:
        league = self._connect()
        try:
            data = league.espn_request.news_get(params={"playerId": espn_player_id})
        except Exception:
            return []
        feed = (data.get("news") or {}).get("feed") or []
        return [
            {"headline": f.get("headline", ""), "story": f.get("story", ""),
             "published": f.get("published", ""), "source": f.get("type", "ESPN")}
            for f in feed[:limit]
        ]


# ---- full fantasy-score history under THIS league's scoring rules --------------
def points_from_raw(raw: dict, scoring_items: list[dict]) -> float:
    """Fallback when ESPN gives raw stats but no applied score: sum(stat value x league points per stat).
    `raw` maps stat id (str) -> value; `scoring_items` are ESPN's league scoringItems."""
    total = 0.0
    for item in scoring_items:
        val = raw.get(str(item["statId"]))
        if val:
            total += float(val) * float(item.get("points", 0) or 0)
    return round(total, 1)


def _history_from_card(card: dict, scoring_items: list[dict]) -> list[dict]:
    out = []
    for st in card["players"][0]["player"].get("stats", []):
        if st.get("statSourceId") != 0 or st.get("statSplitTypeId") != 1 or not st.get("scoringPeriodId"):
            continue                                           # weekly actuals only (not projections / season totals)
        applied = st.get("appliedTotal")
        computed = applied is None and bool(st.get("stats"))
        pts = points_from_raw(st.get("stats", {}), scoring_items) if computed else round(float(applied or 0), 1)
        out.append({"season": int(st["seasonId"]), "week": int(st["scoringPeriodId"]), "points": pts,
                    "source": "computed" if computed else "espn"})
    return sorted(out, key=lambda r: (r["season"], r["week"]))


def _fetch_history(self, player_id: int) -> list[dict]:
    league = self._connect()
    if not hasattr(self, "_scoring_items"):
        raw = league.espn_request.league_get(params={"view": "mSettings"})
        self._scoring_items = raw["settings"]["scoringSettings"].get("scoringItems", [])
    card = league.espn_request.get_player_card([int(player_id)], league.finalScoringPeriod)
    return _history_from_card(card, self._scoring_items)


LeagueClient.fetch_player_history = _fetch_history


def get_player_history(client: LeagueClient, player_id: int, force: bool = False) -> list[dict]:
    """[{season, week, points, source}] oldest->newest, cached 6h. Empty list on failure (UI shows an honest state)."""
    key = f"history:{client.cfg.league_id}:{client.cfg.year}:{player_id}"
    if not force:
        cached = db.cache_get(key, 6 * 3600, client.cfg.db_path)
        if cached is not None:
            return cached
    try:
        hist = client.fetch_player_history(player_id)
    except Exception:
        return []
    db.cache_set(key, hist, client.cfg.db_path)
    return hist


# ---- cached access (what the app calls) -----------------------------------
def get_snapshot(client: LeagueClient, force: bool = False) -> LeagueSnapshot:
    key = f"snapshot:{client.cfg.league_id}:{client.cfg.year}"
    if not force:
        cached = db.cache_get(key, client.cfg.cache_ttl, client.cfg.db_path)
        if cached:
            return LeagueSnapshot.from_dict(cached)
    snap = client.fetch_snapshot()
    db.cache_set(key, snap.to_dict(), client.cfg.db_path)
    return snap


def get_free_agents(client: LeagueClient, position: Optional[str] = None, size: int = 50,
                    force: bool = False) -> list[PlayerInfo]:
    key = f"fa:{client.cfg.league_id}:{client.cfg.year}:{position or 'ALL'}:{size}"
    if not force:
        cached = db.cache_get(key, client.cfg.cache_ttl, client.cfg.db_path)
        if cached is not None:
            return [PlayerInfo.from_dict(p) for p in cached]
    fas = client.fetch_free_agents(position, size)
    db.cache_set(key, [p.__dict__ for p in fas], client.cfg.db_path)
    return fas
