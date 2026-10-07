"""Plain dataclasses that the whole app uses. `league_client` is the only module
that converts espn-api objects into these, so everything else is testable offline."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Statuses that mean "will not play this week".
OUT_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION", "IR", "PUP", "NFI"}
# Statuses worth warning about but still startable.
RISK_STATUSES = {"QUESTIONABLE", "DOUBTFUL"}


@dataclass
class PlayerInfo:
    player_id: int
    name: str
    position: str                      # QB / RB / WR / TE / K / D/ST
    pro_team: str = ""
    injury_status: str = "ACTIVE"      # ESPN-normalized, upper-case
    lineup_slot: str = "BE"            # current slot on fantasy team
    eligible_slots: list[str] = field(default_factory=list)
    week_proj: float = 0.0             # projected fantasy points, current week
    week_points: float = 0.0           # actual points so far this week
    total_points: float = 0.0          # season actual
    games_played: int = 0
    season_proj_ppg: float = 0.0       # ESPN season projection, per game
    percent_owned: float = -1.0
    on_bye: bool = False
    bye_week: int = 0                  # NFL bye week number (0 = unknown)
    opponent: str = ""
    owner_team_id: Optional[int] = None
    game_time: str = ""               # ISO local kickoff time for this week's game ("" = bye/unknown)
    weekly_points: dict[str, float] = field(default_factory=dict)   # {week: actual points} for completed weeks
    # --- edge engine (filled in after load; ESPN's own number is always kept in espn_week_proj) ---
    espn_week_proj: float = 0.0        # ESPN projection before adjustments (0 = no edge applied)
    edge: list = field(default_factory=list)       # this week's adjustments: [{type, delta, reason, source, confidence, at}]
    edge_ros: float = 0.0              # per-game rest-of-season adjustment (points)
    tags: list = field(default_factory=list)       # [(tag, explanation)] e.g. ("buy low", "...")
    context: list = field(default_factory=list)    # informational notes NOT counted in the projection, e.g. an injury cascade [{kind, text, pts}]
    # --- market + injury timeline (trade engine v2) ---
    market: dict = field(default_factory=dict)     # ESPN consensus signals: adp, auction, ppr_rank, ros_pos_rank, owned, started
    return_games: float = -1.0                     # expected additional games missed (from news); -1 = unknown, use status defaults
    added_ts: float = 0.0                          # epoch seconds when MY team added him (0 = unknown / not recent)

    @property
    def edge_total(self) -> float:
        return round(sum(a["delta"] for a in self.edge), 2)

    @property
    def has_edge(self) -> bool:
        return bool(self.edge) and abs(self.edge_total) >= 0.05

    @property
    def actual_ppg(self) -> float:
        return self.total_points / self.games_played if self.games_played else 0.0

    @property
    def is_out(self) -> bool:
        return self.injury_status in OUT_STATUSES

    @property
    def is_risky(self) -> bool:
        return self.injury_status in RISK_STATUSES

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerInfo":
        return cls(**d)


@dataclass
class Owner:
    first_name: str = ""
    last_name: str = ""
    display_name: str = ""


@dataclass
class TeamInfo:
    team_id: int
    name: str
    abbrev: str = ""
    owners: list[Owner] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: float = 0.0
    points_against: float = 0.0
    standing: int = 0
    playoff_pct: float = 0.0
    waiver_rank: int = 0
    roster: list[PlayerInfo] = field(default_factory=list)
    logo: str = ""                    # fantasy team logo URL from ESPN
    faab_spent: float = 0.0

    @property
    def record(self) -> str:
        return f"{self.wins}-{self.losses}" + (f"-{self.ties}" if self.ties else "")

    @property
    def owner_label(self) -> str:
        if not self.owners:
            return ""
        o = self.owners[0]
        full = f"{o.first_name} {o.last_name}".strip()
        return full or o.display_name

    @classmethod
    def from_dict(cls, d: dict) -> "TeamInfo":
        d = dict(d)
        d["owners"] = [Owner(**o) for o in d.get("owners", [])]
        d["roster"] = [PlayerInfo.from_dict(p) for p in d.get("roster", [])]
        return cls(**d)


@dataclass
class MatchupInfo:
    week: int
    home_team_id: Optional[int]
    away_team_id: Optional[int]
    home_score: float = 0.0
    away_score: float = 0.0
    home_proj: float = 0.0
    away_proj: float = 0.0

    def involves(self, team_id: int) -> bool:
        return team_id in (self.home_team_id, self.away_team_id)

    def opponent_of(self, team_id: int) -> Optional[int]:
        if team_id == self.home_team_id:
            return self.away_team_id
        if team_id == self.away_team_id:
            return self.home_team_id
        return None


@dataclass
class LeagueSnapshot:
    league_name: str
    year: int
    week: int                          # current scoring period
    final_week: int                    # last scoring period of the fantasy season
    reg_season_weeks: int
    team_count: int
    my_team_id: int
    starter_slots: dict[str, int]      # ordered, e.g. {"QB":1,"RB":2,"WR":2,"TE":1,"FLEX":1,"D/ST":1,"K":1}
    bench_slots: int = 0
    ir_slots: int = 0
    scoring_notes: dict[str, float] = field(default_factory=dict)   # e.g. {"reception": 1.0}
    faab_budget: int = 0              # 0 = league does not use FAAB
    waiver_days: list[str] = field(default_factory=list)
    teams: list[TeamInfo] = field(default_factory=list)
    matchups: list[MatchupInfo] = field(default_factory=list)
    fetched_at: float = 0.0

    # ---- lookups ---------------------------------------------------------
    def team(self, team_id: int) -> Optional[TeamInfo]:
        return next((t for t in self.teams if t.team_id == team_id), None)

    @property
    def my_team(self) -> TeamInfo:
        t = self.team(self.my_team_id)
        if t is None:
            raise KeyError(f"TEAM_ID {self.my_team_id} not found in league (teams: {[x.team_id for x in self.teams]})")
        return t

    def matchup_for(self, team_id: int) -> Optional[MatchupInfo]:
        return next((m for m in self.matchups if m.involves(team_id)), None)

    def find_team(self, query: str) -> TeamInfo:
        """Find a team by owner first name ('Kaden'), owner full/display name, team name or abbreviation.
        Raises LookupError with a helpful message when nothing / more than one team matches."""
        q = " ".join(query.lower().split())
        if not q:
            raise LookupError("Empty team name.")

        def hits(match) -> list[TeamInfo]:
            return [t for t in self.teams if match(t)]

        def owner_fields(t: TeamInfo):
            for o in t.owners:
                yield from (o.first_name.lower(), f"{o.first_name} {o.last_name}".lower().strip(), o.display_name.lower())

        # exact owner first/full/display name, then exact team name, then looser matches
        stages = [
            lambda t: q in set(owner_fields(t)),
            lambda t: q in (t.name.lower(), t.abbrev.lower()),
            lambda t: any(f.startswith(q) for f in owner_fields(t)),
            lambda t: q in t.name.lower() or any(q in f for f in owner_fields(t)),
        ]
        for stage in stages:
            found = hits(stage)
            if len(found) == 1:
                return found[0]
            if len(found) > 1:
                names = ", ".join(f"{t.name} ({t.owner_label})" for t in found)
                raise LookupError(f"'{query}' matches several teams: {names}. Be more specific.")
        avail = ", ".join(f"{t.owners[0].first_name if t.owners else '?'} = {t.name}" for t in self.teams)
        raise LookupError(f"No team matches '{query}'. Teams: {avail}")

    def find_player(self, query: str, team: Optional["TeamInfo"] = None) -> PlayerInfo:
        """Find a rostered player by (partial) name, optionally restricted to one team."""
        q = " ".join(query.lower().replace(".", "").split())
        pool = team.roster if team else [p for t in self.teams for p in t.roster]
        norm = lambda p: " ".join(p.name.lower().replace(".", "").split())
        found = [p for p in pool if norm(p) == q] or [p for p in pool if q in norm(p)]
        if len(found) == 1:
            return found[0]
        if not found:
            raise LookupError(f"No rostered player matches '{query}'" + (f" on {team.name}." if team else "."))
        raise LookupError(f"'{query}' matches several players: {', '.join(p.name for p in found)}.")

    def standings(self) -> list[TeamInfo]:
        return sorted(self.teams, key=lambda t: (t.standing or 99, -t.wins))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LeagueSnapshot":
        d = dict(d)
        d["teams"] = [TeamInfo.from_dict(t) for t in d.get("teams", [])]
        d["matchups"] = [MatchupInfo(**m) for m in d.get("matchups", [])]
        return cls(**d)
