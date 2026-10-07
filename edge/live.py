"""Glue between the app and the edge engine: shared history cache, league scoring, odds, news events, background news scan."""
from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace
from typing import Callable, Optional

import assets
import db
from edge import engine, news_ai, odds as odds_mod, scoring
from edge.history import Hist, refresh_injuries
from edge.ids import espn_for_gsis
from edge.modules.defense import defense_starters, _prep as _defense_prep
from edge.settings import EdgeSettings

log = logging.getLogger("edge.live")
HIST_TTL = 6 * 3600
_lock = threading.Lock()
_HIST: dict = {"h": None, "at": 0.0, "key": None}
SCANNER = news_ai.BackgroundScanner()


def get_hist(season: int, db_path: Optional[str] = None, force: bool = False) -> Hist:
    """nflverse history for the last two seasons + this one (cached 6h in-process; the disk cache is shared with the backtest)."""
    seasons = [season - 2, season - 1, season]
    with _lock:
        fresh = _HIST["h"] is not None and _HIST["key"] == (tuple(seasons), db_path) and time.time() - _HIST["at"] < HIST_TTL
        if not fresh or force:
            _HIST["h"] = Hist.load(seasons, scoring.weights(path=db_path), with_pbp=True)
            _HIST["at"], _HIST["key"] = time.time(), (tuple(seasons), db_path)
        return _HIST["h"]


def recheck_injuries(season: int, db_path: Optional[str] = None) -> int:
    """Pull the freshest NFL injury report now (called by the 're-check before lock' refresh button)."""
    h = get_hist(season, db_path)
    with _lock:
        return refresh_injuries(h)


def ensure_scoring(client, db_path: Optional[str]) -> str:
    """Store this league's scoring items (once) so the backtest and live engine score players the way ESPN does."""
    if db.setting_get("league_scoring", "", db_path):
        return ""
    try:
        scoring.save_scoring(client.fetch_scoring_items(), db_path)
        return ""
    except Exception as e:
        return f"League scoring couldn't be read ({type(e).__name__}); edges use standard PPR scoring."


def odds_events(db_path: Optional[str], settings: EdgeSettings) -> Optional[list[dict]]:
    names = {t.name: ab for ab, t in assets.nfl_teams(db_path).items()}
    return odds_mod.get_odds(settings, names, db_path)


def events_signature(db_path: Optional[str]) -> str:
    ev = news_ai.load_events(db_path=db_path)
    return f"{len(ev)}:{ev[0]['key'] if ev else ''}"


def run_live(snap, fas: list, sleeper_index, db_path: Optional[str], season: int, week: int, settings: Optional[EdgeSettings] = None) -> engine.EngineResult:
    settings = settings or EdgeSettings()
    h = get_hist(season, db_path)
    players = [p for t in snap.teams for p in t.roster] + list(fas)
    for p in players:
        if not p.espn_week_proj:
            p.espn_week_proj = p.week_proj
    res = engine.run_engine(players, h, season, week, sleeper_index=sleeper_index, news_events=news_ai.load_events(db_path=db_path),
                            odds_events=odds_events(db_path, settings), settings=settings, db_path=db_path)
    if not settings.odds_api_key:
        res.data_status["odds_note"] = "No ODDS_API_KEY: using the Vegas lines in the nflverse schedule (free)."
    return res


# ---- background AI news scan ------------------------------------------------------------------
def news_scan_players(snap, fas: list, edge_res, hist: Hist, my_starters_opps: list[str], per_defense: int = 4, top_fas: int = 40) -> list:
    """All rostered skill players + top free agents + the key defenders my starters will face."""
    ps = [p for t in snap.teams for p in t.roster if p.position in ("QB", "RB", "WR", "TE")]
    ps += sorted([p for p in fas if p.position in ("QB", "RB", "WR", "TE")], key=lambda p: -(p.percent_owned or 0))[:top_fas]
    if hist is not None:
        prep = _defense_prep(hist)
        tw = hist.weekly.t.max() + 1
        for opp in set(my_starters_opps):
            starters = sorted(defense_starters(prep, opp, tw).items(), key=lambda kv: -kv[1][2])[:per_defense]
            for gsis, (name, pos, pct) in starters:
                eid = espn_for_gsis(gsis)
                if eid:
                    ps.append(SimpleNamespace(player_id=eid, name=name, pro_team=opp, position=pos))
    seen, out = set(), []
    for p in ps:
        if p.player_id not in seen:
            seen.add(p.player_id)
            out.append(p)
    return out


def start_news_scan(players: list, fetch_news: Callable, gsis_of: dict[int, str], db_path: Optional[str], run_llm: Callable = news_ai.default_llm) -> bool:
    def make():
        return news_ai.fetch_candidates(players, fetch_news, gsis_of)
    return SCANNER.start(make, run_llm, db_path)
