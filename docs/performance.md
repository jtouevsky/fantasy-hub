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
