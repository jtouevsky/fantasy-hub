from datetime import datetime, timezone

import demo_data
import news
from news import ACT, WATCH, NewsItem, PlayerNews

NOW = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
RECENT, OLD = "2026-10-06T08:00:00Z", "2026-09-20T08:00:00Z"


def _snap():
    snap = demo_data.build_demo_snapshot()
    return snap, snap.my_team


def test_starter_on_bye_or_out_raises_act_alert_with_fix():
    snap, me = _snap()
    qb = next(p for p in me.roster if p.lineup_slot == "QB")
    qb.on_bye = True
    alerts = news.lineup_alerts(snap, me, {}, NOW)
    a = next(a for a in alerts if a.player is qb)
    assert a.severity == ACT and "bye" in a.message and "ESPN app" in a.action
    qb.on_bye = False
    rb = next(p for p in me.roster if p.lineup_slot == "RB")
    rb.injury_status = "OUT"
    assert any(a.player is rb and a.severity == ACT for a in news.lineup_alerts(snap, me, {}, NOW))


def test_sleeper_out_but_espn_active_is_flagged():
    snap, me = _snap()
    wr = next(p for p in me.roster if p.lineup_slot == "WR")
    pn = {wr.player_id: PlayerNews(wr, [], {"injury_status": "Out", "injury_body_part": "Hamstring"})}
    a = next(a for a in news.lineup_alerts(snap, me, pn, NOW) if a.player is wr)
    assert a.severity == ACT and "Sleeper" in a.message


def test_news_flag_requires_player_in_sentence_and_recent_date():
    snap, me = _snap()
    wr = next(p for p in me.roster if p.lineup_slot == "WR")
    last = wr.name.split()[-1]
    roundup = NewsItem("Week 4 winners and losers", "Somebody else was ruled out. " + f"{last} scored twice.", RECENT)
    about = NewsItem(f"{wr.name} limited in practice", f"{last} was limited in practice Wednesday.", RECENT)
    stale = NewsItem(f"{wr.name} ruled out", f"{last} was ruled out.", OLD)
    assert news._flags(PlayerNews(wr, [roundup]), NOW)[0] == []
    assert news._flags(PlayerNews(wr, [stale]), NOW)[0] == []
    assert "limited in practice" in news._flags(PlayerNews(wr, [about]), NOW)[0]
    alerts = news.lineup_alerts(snap, me, {wr.player_id: PlayerNews(wr, [about])}, NOW)
    assert any(a.player is wr and a.severity == WATCH for a in alerts)


def test_get_player_news_caches_and_survives_fetch_errors(tmp_path):
    snap, me = _snap()
    p, calls = me.roster[0], []

    def fetch(pid, n):
        calls.append(pid)
        return [{"headline": "h", "story": "s", "published": RECENT}]

    db_path = str(tmp_path / "n.db")
    assert news.get_player_news(p, fetch, db_path=db_path).items[0].headline == "h"
    news.get_player_news(p, fetch, db_path=db_path)
    assert len(calls) == 1                                  # second call served from cache
    boom = lambda pid, n: (_ for _ in ()).throw(RuntimeError("down"))
    assert news.get_player_news(me.roster[1], boom, db_path=db_path).items == []
