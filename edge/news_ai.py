"""Module 6: turn player news into structured events with Claude, strictly extraction (no added facts).

Pipeline: ESPN player news -> cheap keyword pre-filter -> batches to Claude (your subscription via the Agent SDK, or any injected
callable) -> JSON events -> GUARDRAILS -> SQLite (raw text stored next to the parsed result). Guardrails drop anything the article
doesn't actually support: a status needs a matching phrase in the text, beneficiaries must be named in the text, games-missed must
be a number that appears in the text (or be derivable from 'out for the season'). Parsed events only change injury state used by
the cascade/defense modules and lineup alerts; they never create point adjustments directly.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import db

EVENT_TYPES = {"injury", "practice_status", "role_change", "depth_chart", "suspension", "other"}
STATUSES = {"out", "doubtful", "questionable", "ir", "suspended", "active", None}
RELEVANT = re.compile(r"\b(out|inactive|ruled|doubtful|questionable|injur|ir\b|reserve|practice|limited|dnp|did not|hamstring|ankle|knee|concussion|"
                      r"surgery|suspend|depth chart|starter|starting|promot|demot|snap|workload|expected to|will miss|return)", re.I)
SYSTEM = ("You extract facts from short NFL player news items. You are an extractor, not an analyst. Use ONLY what the text says; "
          "never add, infer or guess facts (no outside knowledge, no predictions). If the text does not state something, use null. "
          "Return ONLY a JSON array, one object per input item, no commentary.")
SCHEMA = ('Each object: {"key": <the item key>, "event_type": one of ["injury","practice_status","role_change","depth_chart","suspension","other"], '
          '"status": one of ["out","doubtful","questionable","ir","suspended","active",null], "expected_games_missed": integer or null, '
          '"beneficiaries": [names of OTHER players the text says will get more work], "summary": one short sentence restating the text}')
_STATUS_PHRASES = {
    "out": [r"\bruled out\b", r"\bwill not play\b", r"\bwon'?t play\b", r"\bout (for|vs|against|this|sunday|monday|thursday|saturday)\b", r"\bis out\b", r"\binactive\b", r"\bsidelined\b", r"\bout\b"],
    "doubtful": [r"\bdoubtful\b"], "questionable": [r"\bquestionable\b", r"\bgame-?time decision\b", r"\bin jeopardy\b", r"\buncertain\b"],
    "ir": [r"\binjured reserve\b", r"\bplaced on ir\b", r"\bon ir\b", r"\bseason-ending\b", r"\bout for the season\b"],
    "suspended": [r"\bsuspend", r"\bsuspension\b"], "active": [r"\bfull participant\b", r"\bcleared\b", r"\bwill play\b", r"\bexpected to play\b", r"\bactivated\b", r"\breturns?\b"],
}


def news_key(player_id, published: str, headline: str) -> str:
    return hashlib.sha1(f"{player_id}|{published}|{headline}".encode()).hexdigest()[:20]


def prefilter(items: list[dict], max_age_days: int = 6, now: Optional[datetime] = None) -> list[dict]:
    """Keep only recent items whose text looks injury/role related; this is what keeps the number of Claude calls small."""
    now = now or datetime.now(timezone.utc)
    out = []
    for it in items:
        try:
            age = now - datetime.fromisoformat(it.get("published", "").replace("Z", "+00:00"))
            if age > timedelta(days=max_age_days):
                continue
        except ValueError:
            continue
        if RELEVANT.search(f"{it.get('headline', '')} {it.get('story', '')}"):
            out.append(it)
    return out


def build_prompt(items: list[dict]) -> str:
    body = "\n\n".join(f'KEY: {it["key"]}\nPLAYER: {it["player_name"]} ({it.get("team", "")})\nHEADLINE: {it["headline"]}\nTEXT: {it["story"][:900]}' for it in items)
    return f"{SCHEMA}\n\nNEWS ITEMS:\n\n{body}\n\nReturn the JSON array now."


def _words_to_int(text: str) -> Optional[int]:
    m = re.search(r"\b(?:miss|out|sidelined)\w*\s+(?:the next\s+)?(\d+|one|two|three|four|five|six|several)\s+(?:more\s+)?(?:games?|weeks?)", text, re.I)
    if not m:
        return None
    w = m.group(1).lower()
    return int(w) if w.isdigit() else {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(w)


def validate_event(ev: dict, text: str, player_name: str) -> dict:
    """Guardrails. Returns a cleaned event; unsupported claims are removed and listed under 'dropped'."""
    t = text.lower()
    dropped = []
    et = ev.get("event_type") if ev.get("event_type") in EVENT_TYPES else "other"
    status = ev.get("status")
    status = status.lower() if isinstance(status, str) else None
    if status not in STATUSES:
        dropped.append(f"unknown status '{status}'")
        status = None
    if status and status != "active" and not any(re.search(p, t) for p in _STATUS_PHRASES.get(status, [])):
        dropped.append(f"status '{status}' not supported by the text")
        status = None
    if status == "active" and not any(re.search(p, t) for p in _STATUS_PHRASES["active"]):
        dropped.append("status 'active' not supported by the text")
        status = None
    games = ev.get("expected_games_missed")
    if isinstance(games, (int, float)):
        games = int(games)
        said = _words_to_int(text)
        season_ending = bool(re.search(r"season-ending|out for the season|rest of the season", t))
        if not ((said is not None and said == games) or (season_ending and games >= 3)):
            dropped.append(f"games missed ({games}) not stated in the text")
            games = None
    else:
        games = None
    bens = []
    for b in ev.get("beneficiaries") or []:
        last = str(b).strip().split()[-1].lower().rstrip(".,") if str(b).strip() else ""
        if last and last in t and last != player_name.split()[-1].lower():
            bens.append(str(b).strip())
        else:
            dropped.append(f"beneficiary '{b}' not named in the text")
    return {"event_type": et, "status": status, "expected_games_missed": games, "beneficiaries": bens, "summary": str(ev.get("summary") or "")[:300], "dropped": dropped}


def parse_response(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("key")]


def default_llm(prompt: str) -> str:
    """One no-tools Claude call through the logged-in Claude Code subscription (no API key)."""
    import asyncio
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    async def go() -> str:
        opts = ClaudeAgentOptions(system_prompt=SYSTEM, tools=[], allowed_tools=[], setting_sources=[], max_turns=1,
                                  env={"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""})
        parts = []
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
        return "".join(parts)
    return asyncio.run(go())


def scan(candidates: list[dict], run_llm: Callable[[str], str] = default_llm, db_path: Optional[str] = None, batch: int = 10,
         now: Optional[datetime] = None) -> list[dict]:
    """candidates: [{player_espn_id, gsis, player_name, team, pos, headline, story, published, url}] (newest item per player first).
    Skips items already parsed (cache). Returns ALL stored events for these items."""
    items = []
    for c in prefilter(candidates, now=now):
        c = dict(c)
        c["key"] = news_key(c["player_espn_id"], c["published"], c["headline"])
        items.append(c)
    with db.connect(db_path) as conn:
        known = {r["news_key"] for r in conn.execute("SELECT news_key FROM news_events WHERE parsed IS NOT NULL OR error IS NOT NULL")}
    todo = [i for i in items if i["key"] not in known]
    for n in range(0, len(todo), batch):
        chunk = todo[n:n + batch]
        by_key = {c["key"]: c for c in chunk}
        try:
            parsed = {d["key"]: d for d in parse_response(run_llm(build_prompt(chunk)))}
            err = None
        except Exception as e:                      # one failed batch must not lose the others
            parsed, err = {}, f"{type(e).__name__}: {e}"[:200]
        with db.connect(db_path) as conn:
            for k, c in by_key.items():
                text = f"{c['headline']} {c['story']}"
                ev = validate_event(parsed[k], text, c["player_name"]) if k in parsed else None
                conn.execute("INSERT OR REPLACE INTO news_events(news_key, player_espn_id, raw_text, parsed, source_url, published_at, parsed_at, error) VALUES(?,?,?,?,?,?,?,?)",
                             (k, c["player_espn_id"], text, json.dumps({**ev, "player": c["player_name"], "team": c.get("team", ""), "pos": c.get("pos", ""), "gsis": c.get("gsis", ""),
                                                                         "headline": c["headline"]}) if ev else None, c.get("url", ""), c["published"], time.time(),
                              err if ev is None else None))
    return load_events([i["key"] for i in items], db_path)


def load_events(keys: Optional[list[str]] = None, db_path: Optional[str] = None, max_age_days: int = 6) -> list[dict]:
    """Parsed events (newest first). Each carries raw_text and source_url so any claim can be traced back to the article."""
    with db.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM news_events WHERE parsed IS NOT NULL ORDER BY published_at DESC").fetchall()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    out = []
    for r in rows:
        if keys is not None and r["news_key"] not in keys:
            continue
        if r["published_at"] and r["published_at"] < cutoff[:19]:
            continue
        ev = json.loads(r["parsed"])
        ev.update(player_espn_id=r["player_espn_id"], source_url=r["source_url"], published_at=r["published_at"], raw_text=r["raw_text"], key=r["news_key"])
        out.append(ev)
    return out


class BackgroundScanner:
    """Runs scans off the UI thread; results land in SQLite and show up on the next rerun. At most one scan at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.last_started = 0.0
        self.last_finished = 0.0
        self.last_error = ""
        self.progress = ""

    def start(self, make_candidates: Callable[[], list[dict]], run_llm: Callable[[str], str] = default_llm, db_path: Optional[str] = None, min_interval: float = 900.0) -> bool:
        with self._lock:
            if self.running or time.time() - self.last_started < min_interval:
                return False
            self.running, self.last_started, self.last_error = True, time.time(), ""
        threading.Thread(target=self._work, args=(make_candidates, run_llm, db_path), daemon=True).start()
        return True

    def _work(self, make_candidates, run_llm, db_path):
        try:
            self.progress = "fetching news"
            cands = make_candidates()
            self.progress = f"reading {len(cands)} news items"
            scan(cands, run_llm, db_path)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"[:200]
        finally:
            self.running, self.last_finished, self.progress = False, time.time(), ""


def fetch_candidates(players: list, fetch_news: Callable[[int, int], list[dict]], gsis_of: dict[int, str], workers: int = 8, per_player: int = 2) -> list[dict]:
    """ESPN news (newest few per player), fetched in parallel. `players` are PlayerInfo-like (player_id, name, pro_team, position)."""
    def one(p):
        try:
            items = fetch_news(p.player_id, per_player)
        except Exception:
            return []
        return [{"player_espn_id": p.player_id, "gsis": gsis_of.get(p.player_id, ""), "player_name": p.name, "team": p.pro_team, "pos": p.position,
                 "headline": i.get("headline", ""), "story": i.get("story", ""), "published": i.get("published", ""), "url": i.get("url", "")} for i in items]
    with ThreadPoolExecutor(workers) as ex:
        return [c for batch in ex.map(one, players) for c in batch]
