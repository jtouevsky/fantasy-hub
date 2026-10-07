"""Baseline profile of the Streamlit app: per-page rerun time (warm), network calls per rerun, and the top recomputation hot spots.
Usage: python -m tools.profile_streamlit  (uses the live league if configured, else set DEMO_MODE=1)"""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import time

import requests
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
PAGES = ["Overview", "My Team", "Matchup", "Players", "Trades", "League", "Assistant", "More"]

calls: list[str] = []
_orig = requests.Session.request


def _spy(self, method, url, *a, **k):
    calls.append(f"{method} {url.split('?')[0][:90]}")
    return _orig(self, method, url, *a, **k)


requests.Session.request = _spy


def main() -> None:
    at = AppTest.from_file(APP, default_timeout=300)
    t = time.perf_counter(); at.run(); cold = time.perf_counter() - t
    print(f"cold first render: {cold:.2f}s, network calls: {len(calls)}")
    rows = []
    for page in PAGES:
        at.session_state["page_req"] = page
        calls.clear()
        t = time.perf_counter(); at.run(); dt = time.perf_counter() - t
        rows.append((page, dt, len(calls), len(at.get("html"))))
    print(f"{'page':10} {'switch (s)':>10} {'net calls':>10} {'html blocks':>12}")
    for r in rows:
        print(f"{r[0]:10} {r[1]:10.2f} {r[2]:10d} {r[3]:12d}")
    at.session_state["page_req"] = "Overview"
    pr = cProfile.Profile(); pr.enable(); at.run(); pr.disable()
    s = io.StringIO(); pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(14)
    print("\nWarm Overview rerun, top cumulative:\n" + "\n".join(l for l in s.getvalue().splitlines() if "fantasy manager" in l or "ncalls" in l)[:2500])


if __name__ == "__main__":
    main()
