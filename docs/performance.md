# Performance: before and after the migration off Streamlit

Machine: the author's MacBook, live league (Week 5, 2026), warm local caches. "Server time" = time to run the page's code; the browser adds transport and paint.

## Before (Streamlit, measured with `streamlit.testing` on the live league)

Every click (tab, filter, button) re-ran the entire script from the top. Measured per tab switch on a warm session:

| Screen | Server time per switch | Network calls during that switch |
|---|---|---|
| Overview | 1.24 s | 0 |
| My Team | 0.10 s | 0 |
| Matchup | 0.08 s | 0 |
| Players | 0.31 s | 1 |
| Trades (cached search) | 0.89 s | 0 |
| League | 1.07 s | 3 |
| Assistant | 0.09 s | 0 |
| More (News tab) | 4.89 s | 31 |
| **First load (cold)** | **20.7 s** | **447** |

What was recomputed on every interaction (found by reading the script path and profiling):
* `load_ctx()` ran on every rerun: re-applied edge adjustments to ~500 players, re-checked cache keys for the edge engine, model and hub, rebuilt the brand/image resolver.
* Image existence checks (`HEAD` requests) for every avatar and logo that had not been seen yet.
* The move engine (`find_moves`) and the trade search ran inside the page script, so they re-ran on any widget change.
* The News tab fetched per-player news for both rosters (31 requests).
* Streamlit also resends and diffs the page's element tree over a websocket on each rerun, on top of the numbers above.

## After (FastAPI + React)

Measured against the same live league.

| What | Time |
|---|---|
| Tab switch in the browser (click to content on screen, cached data) | **0.8 - 25 ms** (JS thread time, 12 switches, 0 skeletons shown) |
| API response, warmed server: overview / team / matchup / players / league / trades meta | 22 / 7 / 5 / 28 / 2 / 6 ms |
| First request of the whole server (ESPN snapshot, edge engine, value model, hub) | ~20 s, now done in the background at startup (first browser load finds it cached) |
| Trade search, first compute | 0.8 s; cached afterwards: 3 ms |
| News tab, API (warm disk cache) | 27 ms first, 3 ms after |
| Network calls per tab switch | 0 once prefetched (every screen's data is warmed after first paint) |
| Frontend payload | main bundle 370 KB (115 KB gzip); Trades, More and Player sheet are lazy chunks (17, 11, 8 KB) preloaded when idle |

How it is fast:
* **Server caches by refresh, not by request.** `ctx.get_ctx()` holds the ESPN snapshot, edge results, value model and hub; it rebuilds only on Refresh or when the data TTL expires. Moves, trade searches, news and histories are memoized on that context, so a new refresh empties them automatically.
* **Client caches and prefetches.** TanStack Query keeps data in memory (5 min fresh) and in `localStorage` between visits (shown instantly, refreshed in the background). After first paint every screen's data and code chunk are prefetched; hovering a tab prefetches too.
* **Cheap rendering.** Client-side routing (no reloads). The free-agent list is virtualized (only visible rows exist in the DOM). Images are `loading="lazy"` at their displayed size, with initials as the failure fallback (no server-side image probing). `backdrop-filter` only on the sticky header and nav pill; no looping animations; rows use `contain: layout paint`.

Reproduce: `make start`, then in the browser console time `document.querySelector('nav a').click()` against `performance.now()`; API timings with `curl -w '%{time_total}' localhost:8000/api/overview`.


## After the UI overhaul (Part 3)

Re-measured in the browser on the live league after adding rings, flaps, metal buttons and the new layouts. Every screen is now in the main bundle (no lazy chunks), so a first visit to any tab never shows a skeleton.

| What | Time |
|---|---|
| Tab switch, click to content (14 switches across all 8 tabs) | **0.9 - 35 ms** (median ~5 ms); the slowest is the first render of the virtualized Players list |
| Skeletons shown on a tab switch | 0 |
| Main bundle | 416 KB (126 KB gzip), all screens included; CSS ~30 KB |
| Elements with `backdrop-filter` | 2: the sticky header and the nav pill (small, fixed) |
| CSS animations running while idle | **0** (checked with `document.getAnimations()`) |

How the effects stay cheap:
* **Rings** are one conic-gradient plus a radial mask; **chrome rims** are a conic-gradient whose angle (a registered `@property`) transitions only on hover or press; the **scoreboard light** moves with the pointer through two CSS variables (one `requestAnimationFrame` per move, only while hovering); **split-flap digits** run a single 240 ms flip, and only the digit that changed re-mounts. No WebGL or shaders anywhere, no looping animations, nothing animates offscreen.
* `prefers-reduced-motion` turns the flips and transitions into static states.
* Dither / ASCII texture is a mask and a text row on the News header only, never behind text.


## After the UI v4 overhaul (fun colors, shapes, motion, full-width layout)

Re-measured in the browser on the live league (final build). View Transitions are on (`document.startViewTransition` present).

| What | Part 1 | After UI v3 | **After UI v4** |
|---|---|---|---|
| Tab switch, click to content (16 switches across all 8 tabs) | 0.8 - 25 ms | 0.9 - 35 ms (median ~5) | **2 - 29.5 ms (median 8.6)** |
| Skeletons on a tab switch (data prefetched) | 0 | 0 | 0 |
| Main JS bundle | 370 KB (115 KB gzip) | 416 KB (126 KB gzip) | **425 KB (129 KB gzip)** |
| CSS | ~21 KB | ~30 KB | 41 KB (9.5 KB gzip) |
| Font payload | Google Fonts, third-party requests, 4 families | same | **self-hosted Latin subsets, 92 KB total** (Barlow Condensed 700/800 about 15 KB each, preloaded; one Geist variable file 29 KB; icon font subset to the glyphs used, 13 KB) |
| Elements with `backdrop-filter` | 0 | 2 (header, nav) | **0** |
| CSS animations running while idle | 0 | 0 | **0** (checked after the page settled) |
| Animation libraries | none | none | **none** (springs are CSS `linear()` easing; page changes use the View Transitions API) |

The median moved from about 5 to 8.6 ms because a page change now runs inside a view transition (one extra frame to capture the old page), which buys the cross-fade and the portrait morph; it is still about a tenth of the 100 ms budget. No effect was dropped for speed.

Rules the v4 motion follows: only `transform` and `opacity` animate; micro-interactions are 120 to 200 ms and transitions at most 300 ms (page change 110 ms out, 220 ms in; portrait morph 300 ms); the entrance stagger plays on the first load only (a flag removed about 1.8 s after load); tickers and celebrations run once per change and not at all under `prefers-reduced-motion`; headshots are served at the rendered size (120 px wide for avatars up to 46 px, 240 px for larger ones, about 10 KB and 38 KB) instead of one large image.
