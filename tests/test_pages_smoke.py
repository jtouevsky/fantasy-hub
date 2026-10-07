"""Every page renders on demo data without an exception (Streamlit AppTest)."""
import os

import pytest
from streamlit.testing.v1 import AppTest

PAGES = ["Overview", "My Team", "Matchup", "Players", "Trades", "League", "Assistant", "More"]


@pytest.fixture(autouse=True)
def demo(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"), default_timeout=60)
    at.session_state["page_req"] = page
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_trades_modes_render():
    at = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"), default_timeout=60)
    at.session_state["page_req"] = "Trades"
    at.run()
    for mode in ("Evaluate a deal", "Negotiation log", "Find me a trade"):
        at.session_state["tr_mode"] = mode
        at.run()
        assert not at.exception, (mode, [e.value for e in at.exception])


@pytest.mark.parametrize("tab", ["My strategy", "Edge engine", "Recommendation log"])
def test_more_tabs_render(tab):
    at = AppTest.from_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"), default_timeout=60)
    at.session_state["page_req"] = "More"
    at.run()
    at.session_state["more_sel"] = tab
    at.run()
    assert not at.exception, (tab, [e.value for e in at.exception])
