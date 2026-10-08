"""Screenshots of every screen at several sizes and both themes (the UI audit), driven through Chrome's DevTools protocol so phone widths are real.

    python -m tools.screens docs/ui-v4/after                  # every screen x size x theme
    python -m tools.screens /tmp/shots --only 1440 --theme dark --screen team

Needs Google Chrome and the app on http://localhost:8000. Pages are captured after the data has loaded and the entrance animation is over, full height (capped),
then converted to compact JPEGs with macOS `sips`.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333
SCREENS = {"overview": "/", "team": "/team", "matchup": "/matchup", "players": "/players", "trades": "/trades", "league": "/league", "assistant": "/assistant", "more": "/more"}
SIZES = {"390": (390, 844), "820": (820, 1180), "1440": (1440, 900), "1920": (1920, 1080)}
MAX_H = 2600


class Cdp:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, method: str, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})


async def capture(url: str, out_png: str, w: int, h: int) -> None:
    tab = json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")).read())
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=64 * 2**20) as ws:
        c = Cdp(ws)
        await c.call("Page.enable")
        await c.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=w < 600)
        await c.call("Page.navigate", url=url)
        t0 = time.time()
        while time.time() - t0 < 25:                      # wait for real content (header band present, no skeletons)
            r = await c.call("Runtime.evaluate", expression="!!document.querySelector('.band h1') && !document.querySelector('.content .skel') && document.fonts.status === 'loaded'", returnByValue=True)
            if r["result"].get("value"):
                break
            await asyncio.sleep(0.4)
        await asyncio.sleep(2.4)                          # entrance stagger and image loads
        dims = (await c.call("Runtime.evaluate", expression="[document.documentElement.scrollWidth, Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)]", returnByValue=True))["result"]["value"]
        height = min(max(dims[1], h), MAX_H)
        shot = await c.call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip={"x": 0, "y": 0, "width": w, "height": height, "scale": 1})
        with open(out_png, "wb") as f:
            f.write(base64.b64decode(shot["data"]))
        open(out_png + ".w", "w").write(str(dims[0]))
    urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/close/{tab['id']}").read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--only")
    ap.add_argument("--theme", choices=["light", "dark"])
    ap.add_argument("--screen")
    ap.add_argument("--base", default="http://localhost:8000")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    prof = tempfile.mkdtemp()
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version").read()
                break
            except Exception:
                time.sleep(0.2)
        n, overflow = 0, []
        for theme in ([a.theme] if a.theme else ["light", "dark"]):
            for size, (w, h) in SIZES.items():
                if a.only and size != a.only:
                    continue
                for name, path in SCREENS.items():
                    if a.screen and name != a.screen:
                        continue
                    png = os.path.join(a.out, f"{name}-{size}-{theme}.png")
                    asyncio.run(capture(f"{a.base}{path}{'&' if '?' in path else '?'}theme={theme}", png, w, h))
                    sw = int(open(png + ".w").read()); os.remove(png + ".w")
                    if sw > w + 1:
                        overflow.append(f"{name}-{size}-{theme}: scrollWidth {sw} > {w}")
                    jpg = png[:-4] + ".jpg"
                    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "55", "--resampleWidth", str(min(w, 900)), png, "--out", jpg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    os.remove(png)
                    n += 1
        print(f"{n} screenshots in {a.out}")
        if overflow:
            print("HORIZONTAL OVERFLOW:\n  " + "\n  ".join(overflow))
    finally:
        chrome.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
