import io

import pandas as pd
import pytest
from PIL import Image

import assets
import ctx as cx
import db
import ui
from edge import usage
from edge.history import Hist
from models import TeamInfo


def _jpeg(w=450, h=450, color=(200, 30, 30)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG")
    return b.getvalue()


class Resp:
    def __init__(self, content=b"", status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_custom_fantasy_logo_is_fetched_with_cookies_and_embedded_as_a_small_data_uri(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(assets.requests, "get", lambda url, cookies=None, timeout=0: seen.update(url=url, cookies=cookies) or Resp(_jpeg(500, 300)))
    p = str(tmp_path / "l.db")
    src = assets.fantasy_logo_src("https://mystique.example/img/abc", {"espn_s2": "SECRET", "SWID": "{X}"}, p)
    assert src.startswith("data:image/jpeg;base64,") and seen["cookies"]["espn_s2"] == "SECRET"
    assert len(src) < 40000                                                       # resized, not the full 450px original
    seen.clear()
    assert assets.fantasy_logo_src("https://mystique.example/img/abc", None, p) == src and not seen    # cached: no second download


def test_unavailable_logo_falls_back_cleanly_and_is_not_retried(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(assets.requests, "get", lambda *a, **k: calls.append(1) or Resp(status=401))
    p = str(tmp_path / "l.db")
    assert assets.fantasy_logo_src("https://x/y", None, p) is None and assets.fantasy_logo_src("https://x/y", None, p) is None
    assert len(calls) == 1
    b = ui.Brand(p)
    html = b.team_avatar(TeamInfo(3, "Caleb diggs little kids", logo="https://x/y"))
    assert "<img" not in html and "CK" in html                                    # initials fallback


def test_secrets_never_appear_in_markup(tmp_path, monkeypatch):
    monkeypatch.setattr(assets.requests, "get", lambda *a, **k: Resp(_jpeg()))
    b = ui.Brand(str(tmp_path / "l.db"), {"espn_s2": "SUPERSECRET", "SWID": "{ABC}"})
    html = b.team_avatar(TeamInfo(1, "Team", logo="https://mystique.example/i"))
    assert "SUPERSECRET" not in html and "{ABC}" not in html and "data:image/jpeg" in html


def test_default_svg_logo_is_used_directly(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_exists", lambda u: True)
    html = ui.Brand(str(tmp_path / "l.db")).team_avatar(TeamInfo(8, "Jordy", logo="https://g.espncdn.com/x/default_logos/16.svg"))
    assert 'src="https://g.espncdn.com/x/default_logos/16.svg"' in html and 'role="img"' in html


def test_usage_summary_only_reports_what_the_data_has():
    w = pd.DataFrame([dict(gsis="G", season=2026, week=w, t=202600 + w, team="AAA", carries=0, targets=8 + w, target_share=0.25, pts=10) for w in (1, 2, 3)]
                     + [dict(gsis="O", season=2026, week=w, t=202600 + w, team="AAA", carries=20, targets=2, target_share=0.05, pts=9) for w in (1, 2, 3)])
    sn = pd.DataFrame([dict(gsis="G", season=2026, t=202600 + w, offense_pct=0.8 + 0.02 * w) for w in (1, 2, 3)])
    xf = pd.DataFrame([dict(gsis="G", season=2026, t=202600 + w, xfp=14.0, xfp_actual=11.0) for w in (1, 2, 3)])
    h = Hist([2026], w, pd.DataFrame(), sn, pd.DataFrame(), xf)
    u = usage.usage_summary(h, "G", 2026, 202604)
    assert u["games"] == 3 and u["targets_pg"] == pytest.approx(10.0) and u["target_share"] == pytest.approx(0.25)
    assert u["snap_share"] == pytest.approx(0.84) and u["snap_share_last2"] == pytest.approx(0.85) and u["xfp_pg"] == 14.0 and u["actual_pg"] == 11.0
    assert "carries_pg" in u and usage.usage_summary(h, "NOBODY", 2026, 202604) == {}
    labels = [c[1] for c in usage.usage_cells(u, "WR")]
    assert "Snap share" in labels and "Targets / game" in labels and "Carries / game" not in labels
    assert usage.usage_summary(h, "G", 2026, 202601) == {}                       # nothing before week 1: no invented numbers


def test_watchlist_toggle_persists(tmp_path):
    p = str(tmp_path / "w.db")
    assert cx.load_watchlist(p) == set()
    assert cx.toggle_watch(4430807, p) is True and cx.toggle_watch(3139477, p) is True
    assert cx.load_watchlist(p) == {4430807, 3139477}
    assert cx.toggle_watch(4430807, p) is False and cx.load_watchlist(p) == {3139477}
