"""Headless screenshots of every screen at several sizes and both themes (for the UI audit).

    python -m tools.screens docs/ui-v4/before            # all combinations
    python -m tools.screens /tmp/shots --only 1440 --theme dark

Needs Google Chrome and the app running on http://localhost:8000. Output is converted to small JPEGs with macOS `sips`.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SCREENS = {"overview": "/", "team": "/team", "matchup": "/matchup", "players": "/players", "trades": "/trades", "league": "/league", "assistant": "/assistant", "more": "/more"}
SIZES = {"390": (390, 1500), "820": (820, 1500), "1440": (1440, 1400), "1920": (1920, 1400)}


def shoot(url: str, out_png: str, w: int, h: int) -> None:
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}", "--virtual-time-budget=12000", f"--screenshot={out_png}", url],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--only", help="one size key, e.g. 1440")
    ap.add_argument("--theme", choices=["light", "dark"])
    ap.add_argument("--screen")
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    n = 0
    for theme in ([a.theme] if a.theme else ["light", "dark"]):
        for size, (w, h) in SIZES.items():
            if a.only and size != a.only:
                continue
            for name, path in SCREENS.items():
                if a.screen and name != a.screen:
                    continue
                png = os.path.join(a.out, f"{name}-{size}-{theme}.png")
                shoot(f"{a.base}{path}{'&' if '?' in path else '?'}theme={theme}", png, w, h)
                if os.path.exists(png):
                    jpg = png[:-4] + ".jpg"
                    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "55", "--resampleWidth", str(min(w, 900)), png, "--out", jpg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    os.remove(png)
                    n += 1
    print(f"{n} screenshots in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
