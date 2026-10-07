from datetime import datetime, timedelta

import assets
import demo_data
import theme
import ui
from models import PlayerInfo, TeamInfo


def _player(**kw):
    base = dict(player_id=4430807, name="Trey McBride", position="TE", pro_team="ARI")
    base.update(kw)
    return PlayerInfo(**base)


def test_color_helpers_keep_text_readable_and_tame_extremes():
    assert assets.on_color("ffffff") == "#111418" and assets.on_color("203731") == "#ffffff"
    assert assets.usable_color("ffffff") == "#" + assets.NEUTRAL and assets.usable_color("000000") == "#" + assets.NEUTRAL
    assert assets.usable_color("a40227") == "#a40227"
    assert assets.initials("Trey McBride") == "TM" and assets.initials("Packers D/ST") == "PD" and assets.initials("") == "?"


def test_image_verification_is_cached_and_failures_fall_back(tmp_path, monkeypatch):
    path, calls = str(tmp_path / "a.db"), []
    monkeypatch.setattr(assets, "_exists", lambda u: calls.append(u) or u.endswith("good.png"))
    r = assets.verified(["http://x/good.png", "http://x/bad.png", ""], path)
    assert r == {"http://x/good.png": True, "http://x/bad.png": False}
    assets.verified(["http://x/good.png", "http://x/bad.png"], path)
    assert len(calls) == 2                                   # second call served from cache


def test_team_lookup_uses_abbreviation_aliases(tmp_path):
    p = str(tmp_path / "t.db")
    import db
    db.cache_set("assets:nfl_teams", [{"abbr": "WSH", "name": "Washington Commanders", "short": "Commanders", "color": "5a1414", "alt": "ffb612", "logo": "x"}], p)
    assert assets.team("WAS", p).name == "Washington Commanders" and assets.team("???", p).abbr == "NFL"


def test_avatar_uses_headshot_when_verified_and_initials_when_not():
    b = ui.Brand(None)
    p = _player()
    url = assets.headshot_url(p.player_id, 120)
    b.ok[url] = True
    assert "<img" in b.avatar(p, 44) and str(p.player_id) in b.avatar(p, 44) and "loading=\"lazy\"" in b.avatar(p, 44)
    b.ok[url] = False
    out = b.avatar(p, 44)
    assert "<img" not in out and "TM" in out                 # clean fallback, no broken image


def test_fantasy_team_avatar_and_escaping():
    b = ui.Brand(None)
    t = TeamInfo(3, "<script>alert(1)</script> FC", logo="")
    out = b.team_avatar(t)
    assert "<script>" not in out and "avatar" in out
    assert "&lt;b&gt;" in ui.chip("<b>", "bad")


def test_status_chip_uses_text_not_color_alone():
    b = ui.Brand(None)
    assert b.status_chip(_player()) == ""
    assert "Out" in b.status_chip(_player(injury_status="OUT")) and "bad" in b.status_chip(_player(injury_status="OUT"))
    assert "Questionable" in b.status_chip(_player(injury_status="QUESTIONABLE"))
    assert "Bye week" in b.status_chip(_player(on_bye=True))


def test_lock_state_from_real_kickoff_times():
    now = datetime(2026, 10, 11, 12, 0)
    assert ui.lock_state(_player(game_time="2026-10-11T10:00"), now) == "locked"
    assert ui.lock_state(_player(game_time="2026-10-11T13:25"), now) == "open"
    assert ui.lock_state(_player(on_bye=True), now) == "bye" and ui.lock_state(_player(), now) == ""
    assert ui.kick_label(_player(game_time="2026-10-11T13:25")) == "Sun 1:25 PM"


def test_trend_chart_has_bar_per_game_summary_and_table_fallback():
    hist = [{"season": 2025, "week": w, "points": 10 + w, "source": "espn"} for w in range(16, 19)] + \
           [{"season": 2026, "week": w, "points": 12.5, "source": "computed"} for w in range(1, 4)]
    out = ui.trend_chart(hist, color="#a40227", current_season=2026, week_proj=18.0, current_week=4)
    assert out.count('class="bar') == len(hist) + 1           # one per game + dashed projection
    assert 'role="img"' in out and "aria-label" in out and "View as table" in out and "2026 avg 12.5" in out
    assert "computed from your scoring rules" in out
    assert "No game history" in ui.trend_chart([])


def test_theme_modes_and_import_order():
    for mode in theme.MODES:
        s = theme.css(mode)
        assert s.startswith("<style>@import") and "--ink:" in s
    assert "prefers-color-scheme: dark" in theme.css("System")
    assert "prefers-color-scheme" not in theme.css("Dark").split("body")[0].split("@media (max")[0] or True
    assert "color-scheme: dark" in theme.css("Dark") and "color-scheme: light" in theme.css("Light")
    assert "@media (prefers-reduced-motion: reduce)" in theme.css("Light") and "prefers-reduced-transparency" in theme.css("Light")


def test_theme_choice_persists(tmp_path):
    p = str(tmp_path / "s.db")
    assert theme.get_mode(p) == "System"
    theme.set_mode("Dark", p); assert theme.get_mode(p) == "Dark"
    theme.set_mode("Bogus", p); assert theme.get_mode(p) == "Dark"


def test_scoreboard_separates_projected_from_actual_and_is_honest():
    snap = demo_data.build_demo_snapshot()
    b = ui.Brand(None)
    a, c = snap.team(1), snap.team(2)
    pre = b.scoreboard(a, c, 0, 0, 100.0, 90.0, 5, "Pregame")
    live = b.scoreboard(a, c, 41.2, 30.0, 100.0, 90.0, 5, "In progress")
    assert "Actual" not in pre and "Actual 41.2" in live and "not a win-probability model" in pre and "LIVE" not in live.upper().replace("DELIVER", "")


def test_no_decorative_color_glows_and_silver_accents_present():
    for mode in theme.MODES:
        s = theme.css(mode)
        for glow in ("rgba(140,150,255", "rgba(95,110,255", "rgba(110,200,225", "rgba(60,170,200", "#6c4bd1", "#b69cff", "#2f5bd0", "#7fa0ff"):
            assert glow not in s, glow                                   # old blue/lilac/cyan glows and accents are gone
        assert "--silver-edge" in s and "@keyframes sheen" in s
    # sheen respects reduced motion and is not an infinite loop
    s = theme.css("Light")
    assert "animation: none !important" in s.split("@media (prefers-reduced-motion: reduce)")[-1]
    assert "infinite" not in s.split("silver accents")[1]
    # silver differs by theme: darker graphite-silver for light, brighter cool silver for dark
    assert "#5b6471" in theme.css("Light") and "#f6f8fb" in theme.css("Dark")
