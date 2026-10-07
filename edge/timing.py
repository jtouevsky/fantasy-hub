"""Module 7: timing awareness. Questionable tags are resolved late; inactives come out ~90 minutes before kickoff."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

INACTIVES_BEFORE_KICKOFF = timedelta(minutes=90)
GTD = ("Questionable", "Doubtful")


def _kickoff(p) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(p.game_time) if p.game_time else None
    except ValueError:
        return None


def inactives_at(kickoff: datetime) -> datetime:
    return kickoff - INACTIVES_BEFORE_KICKOFF


def fmt(dt: datetime) -> str:
    return dt.strftime("%a %-I:%M %p")


def timing_alerts(players: list, edge=None, now: Optional[datetime] = None, horizon_hours: float = 72.0) -> list[dict]:
    """`players`: my roster (PlayerInfo with lineup_slot / game_time). `edge`: EngineResult (optional).
    Flags (1) my starters with game-time decisions, and (2) key teammates whose status could change a starter's role.
    Each alert says WHEN the answer arrives (inactives) and what to re-check before lock."""
    now = now or datetime.now()
    starters = [p for p in players if p.lineup_slot not in ("BE", "IR") and p.position != "D/ST"]
    alerts: list[dict] = []
    states = (edge.injuries if edge else {})
    gsis_of = (edge.gsis_of if edge else {})
    seen = set()
    for p in starters:
        ko = _kickoff(p)
        if not ko or ko <= now or ko - now > timedelta(hours=horizon_hours):
            continue
        st = states.get(gsis_of.get(p.player_id, ""))
        status = st.status if st else {"QUESTIONABLE": "Questionable", "DOUBTFUL": "Doubtful"}.get(p.injury_status)
        if status in GTD:
            seen.add(p.player_id)
            ia = inactives_at(ko)
            alerts.append({"kind": "gtd", "player_id": p.player_id, "player": p.name, "status": status, "kickoff": ko, "inactives_at": ia,
                           "hours_to_inactives": round((ia - now).total_seconds() / 3600, 1),
                           "message": f"{p.name} is {status}. Inactives post around {fmt(ia)}; re-check before lock ({fmt(ko)}) and have a backup ready.",
                           "severity": "act" if status == "Doubtful" else "watch"})
    if edge:
        by_id = {p.player_id: p for p in starters}
        espn_of = {v: k for k, v in gsis_of.items()}
        for c in edge.cascades:
            for a in c["absent"]:
                if a["status"] not in GTD:
                    continue
                for b in c["beneficiaries"]:
                    pid = b.get("espn_id")
                    if pid in by_id and b["weekly_pts"] >= 0.5 and espn_of.get(a["gsis"]) not in by_id:
                        ko = _kickoff(by_id[pid])
                        if not ko or ko <= now:
                            continue
                        ia = inactives_at(ko)
                        alerts.append({"kind": "teammate", "player_id": pid, "player": by_id[pid].name, "status": a["status"], "kickoff": ko, "inactives_at": ia,
                                       "hours_to_inactives": round((ia - now).total_seconds() / 3600, 1),
                                       "message": f"{a['name']} ({a['status']}) is a teammate of your starter {by_id[pid].name}: if he sits, {by_id[pid].name} gains about {b['weekly_pts']:+.1f} pts. "
                                                  f"Inactives ~{fmt(ia)}.", "severity": "watch"})
    alerts.sort(key=lambda a: (a["inactives_at"], a["severity"] != "act"))
    return alerts
