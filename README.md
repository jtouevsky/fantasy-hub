# Fantasy Hub

A personal, **read-only** team-manager for an ESPN fantasy football league: dashboard, lineup optimizer,
waiver suggestions, trade analyzer/finder, news, and an AI chat agent. It never changes your roster -
every recommendation ends with something for you to do by hand in the ESPN app.

> **Not affiliated with ESPN, the NFL, Sleeper or Anthropic.** Team logos and player photos are loaded from their public CDNs at runtime and are not bundled. The app only *reads* your own league using your own ESPN cookies (kept in a git-ignored `.env`); nothing about your league is stored in this repository. Fantasy projections and trade advice are estimates, not guarantees. MIT licensed (see `LICENSE`).

## Setup

You need Python 3.11+ and Node.js 20+ (for the frontend build).

```bash
cp .env.example .env        # then edit .env (it is git-ignored)
make setup                  # creates .venv, installs Python and Node dependencies
```

### Fill in `.env`

| Variable | Where to get it |
|---|---|
| `LEAGUE_ID` | The number in your league URL: `fantasy.espn.com/football/league?leagueId=`**`123456`** |
| `TEAM_ID` | Open your team page; the URL has `teamId=`**`N`**. |
| `YEAR` | Season year, e.g. `2026`. |
| `ESPN_S2`, `SWID` | Browser cookies, see below. |
| `ANTHROPIC_MODEL` | Model for the AI chat. Defaults to `claude-sonnet-5-5`. |
| `CHAT_BACKEND` / `ANTHROPIC_API_KEY` | **Optional.** By default the chat uses your Claude subscription (no key). Set `CHAT_BACKEND=api` plus a key to use the pay-per-use API instead. |

### Getting the ESPN cookies (`ESPN_S2` and `SWID`)

1. Log in to ESPN in Chrome and open your league page on `fantasy.espn.com`.
2. Open DevTools (`Cmd+Option+I`) -> **Application** tab -> **Cookies** -> `https://www.espn.com`
   (Safari: Develop -> Show Web Inspector -> Storage -> Cookies. Firefox: Storage tab).
3. Copy the **Value** of the cookie named `espn_s2` -> `ESPN_S2` in `.env`.
4. Copy the **Value** of the cookie named `SWID` (including the curly braces) -> `SWID` in `.env`.

These are effectively your ESPN login. Keep them in `.env` only; never paste them into chat, issues or commits.
They expire eventually - if you get "ESPN denied access", re-copy them.

### Verify the connection

```bash
python check_connection.py     # prints league structure, never your secrets
```

## Run

```bash
make start     # builds the frontend and serves everything at http://localhost:8000
make dev       # development: API on :8000 (auto-reload) + Vite on :5173 (hot reload); open http://localhost:5173
```

Or double-click **Start Fantasy Hub.command** (builds the first time, then opens http://localhost:8000).

No credentials yet? Click **Explore with demo data** on the first screen to explore with a fake league.

### Architecture

* `server/` - FastAPI backend that exposes the existing Python engines (league client, valuation, optimizer, trades, edge engine, agent) as JSON. The ESPN snapshot, edge engine, value model and move/trade engines are built **once per refresh** and cached (`ctx.py`); heavy results (trade search, moves) are memoized per refresh, so navigating never recomputes anything.
* `web/` - React + TypeScript + Vite (TanStack Query for client caching and prefetching, TanStack Virtual for long lists). Client-side routing means switching tabs never reloads data; cached data shows instantly and refreshes in the background.
* Performance numbers: [docs/performance.md](docs/performance.md).

## What's in the app

| Page | What it does |
|---|---|
| **Overview** | The weekly hub: matchup scoreboard (projected vs actual), lineup status, next lineup lock, what needs attention (lineup swaps, waiver moves, roster news), league standing. |
| **My Team** | Starters / bench / IR as compact rows with headshots, opponent, kickoff time, bye/injury/lock status. *Preview the optimal lineup* shows where players would move. Read-only: changes are made in the ESPN app. |
| **Matchup** | Both teams' starters head to head by slot, with a clear "projected vs actual" split and how many starters have yet to play. |
| **Players** | Suggested add/drop moves, then every free agent with filters (position, healthy only, search) and sorts (rest of season, this week, Sleeper trending). Shows waiver priority and FAAB when your league uses them. |
| **Trades** | *Find me a trade* (target team, the player you're offering, a target split like 60/40) or *evaluate* a specific deal, shown as two-sided offer cards with a value meter and each team's lineup impact. |
| **League** | Standings and this week's projected slate. |
| **Assistant** | Chat with Claude (your subscription), with the league/week/scoring context shown. |
| **More** | News and injury alerts for your roster and your opponent's, and the recommendation log. |

**Player sheet** - click any row (or search with `/` or `Cmd/Ctrl+K`) for a portrait, team, ownership, a **fantasy-points-by-game chart under your league's scoring** (2025 + 2026, from ESPN's scored weekly stats; if a week ever has raw stats but no score, the points are computed from your scoring rules and labelled), news, lineup/waiver/trade context, a side-by-side compare, and AI buttons.

**AI everywhere it matters** - "Ask AI why" / "Explain projection" / "Review my lineup" / "Summarize news" buttons open a sheet that shows the context used, the AI's answer (labelled *AI advice*), what tools it looked up, and when it was written. The AI never changes anything; it can't.

Everything is **read-only**. Each recommendation ends with what to do in the ESPN app.

## Design system

* **Light / Dark / System** (the slider icon top-right; remembered in the local database). Optional **accent team** tints selected states with an NFL team's color.
* **Brand data by stable IDs** - NFL names, abbreviations, colors and logos come from ESPN's public team directory (cached 30 days); headshots come from ESPN's CDN by ESPN player id and lazy-load at their displayed size. A missing photo or logo becomes initials instead of a broken image. Defenses use team logos. Fantasy-team logos that need your ESPN cookies are fetched server-side and served from `/api/img/fteam/<id>`; the cookies never reach the browser.
* **Fast by construction** - flat surfaces; `backdrop-filter` only on the small sticky header and nav pill, never on scrolling areas; no looping animations; skeleton loaders only on a cold first visit.
* **Type** - Geist (UI), Barlow Semi Condensed (scores, team and player names), tabular numerals for every score and projection. Fonts load from Google Fonts; offline it falls back to system fonts.
* **Responsive** - rows, scoreboards and trade cards restack on phones.
* Source: `web/src/styles.css` (tokens + components), `web/src/ui.tsx` (shared components), `theme.py` (saved preferences), `assets.py`.

### Known limits (need new data or backend work, so not faked)

* No live-score feed: scores update when you press **Refresh** (cache TTL applies); the app says "Updated N min ago" instead of "LIVE".
* No win-probability model (the scoreboard says it's ESPN's projections only).
* One league at a time (configured in `.env`).
* No usage/opportunity metrics (snaps, targets) or per-game opponent history; the chart shows fantasy points only.
* No league activity feed or waiver-claim deadlines beyond the waiver days ESPN reports.
* Lineup/waiver/trade changes can't be submitted from here (by design).

## Edge engine: finding what ESPN's projections miss

The edge engine never replaces ESPN. It adds explainable, capped adjustments on top:

```
adjusted_projection = ESPN projection + sum(adjustments)          each adjustment = player, week, type, points, reason, source, timestamp, confidence
```

* **Where you see it:** every adjusted number reads **"ESPN 12.4 → Adjusted 14.9"** with an expandable *why* (each adjustment's size, plain-English reason, source, confidence, time, and its uncapped size if the cap bit). Rows, the player sheet, recommendation cards, the lineup optimizer (swaps are labeled when they exist *because of* an edge, with the ESPN-only value shown), the waiver ranker (reason text leads with the edge), and the trade analyzer (rest-of-season edges feed player value; buy-low/sell-high tags tilt the ranking). **More → Edge engine** shows data-source status, each module's verdict, every adjustment, cascades and game environments.
* **Never fabricated:** if a data source is missing the player gets *no* adjustment and the UI says so. Everything is stored in SQLite (`adjustments` table); total movement per player-week is capped at `EDGE_CAP_PCT` (35%) of `max(ESPN projection, EDGE_CAP_FLOOR)` (floor 6 pts so a 2-point backup can still move; set the floor to 0 for a strict percentage cap).

### Modules and what the backtest says

Backtested on 2024 (tuning) and 2025 (held out) in *your league's scoring*; full tables, ablations and caveats in [`docs/backtest.md`](docs/backtest.md) (regenerate with `python -m edge.backtest`). Baseline = trailing 4-game average, because historical ESPN projections aren't available; **gains over real ESPN projections will be smaller**.

| # | Module | Verdict | What helped / didn't |
|---|---|---|---|
| 1 | Injury cascade (vacated opportunity) | **Context only** | Directionally right when a key starter is confirmed out (backups did even better than predicted), but under every filter and threshold we tried it did **not** improve weekly accuracy over recent form, so it is shown as labeled context ("not in projection") and does **not** move projections. See the diagnostics table. |
| 2 | Opposing defense injuries, own OL injuries, pass rush | **ON** | Nearly all the gain is *your own offensive linemen being out*. Opposing DB / pass-rusher injuries help slightly; the play-by-play pressure matchup added nothing measurable. (OL aren't in snap counts, so listed OL are counted, not "starters".) |
| 3 | Vegas game environment | **ON (small)** | Small but statistically clear. Free nflverse schedule lines are used unless `ODDS_API_KEY` is set (cached ~12h; ~4 of ~500 monthly credits per day). |
| 4 | Weather | **ON** | Wind >= 15 mph / extreme cold at outdoor stadiums cut QB/WR/TE scoring; clear gain on the games it touches. Domes and retractable roofs get none. Validated with *actual* wind (a forecast proxy) so live effects will be noisier; precipitation is shown but untested. |
| 5 | Opportunity vs. production (xFP) | **ON** | The strongest module. **Tags are validated:** "buy low" players beat their baseline by about +2.1 pts the next game, "sell high" players fell short by about 4.0 pts. "Role growing" (snap-share trend) is **not** predictive on its own, so it's informational only. |
| 6 | AI news scanning | not backtestable | Claude (your subscription) turns ESPN news into structured events (status, games missed, who benefits). It only *extracts*: any status, games-missed count or beneficiary the article text doesn't support is dropped (guardrails + tests), raw text and source link are stored, and items about games already played are ignored. Parsed events update injury state and alerts; they never create point adjustments by themselves. Runs in a background thread. |
| 7 | Timing | n/a | Flags your starters (and key teammates) with game-time decisions, shows when inactives post (~90 min before kickoff), and **Re-check injuries & re-run edges** re-pulls injury sources and re-runs the optimizer. |

Live strengths are the backtest strengths times a documented haircut (`LIVE_SCALE` in `edge/backtest.py`: Vegas 0.5, defense 0.75, regression 0.5, weather 1.0), because ESPN already absorbs part of these signals. These multipliers are judgment calls, not measurements. The rest-of-season schedule adjustment (remaining opponents' strength, capped at +/-3%) is **not backtested** and is labeled low confidence.

### Data sources
`nflreadpy` (the maintained successor to `nfl_data_py`; stats, play-by-play, snaps, injuries, schedules/lines, `ff_opportunity`, `ff_playerids`), Sleeper (injuries, depth chart order, trending), ESPN (projections, rosters, news), The Odds API (optional), Open-Meteo (weather, no key). Players are matched by a stored ESPN <-> Sleeper <-> GSIS crosswalk; name+team+position matching is a last resort and is logged.

### Deliberately excluded
* **QB handedness, height/weight/40-time as weekly adjustments:** low signal, and whatever signal exists is already reflected in usage and results.
* **Raw "defense vs. position" rankings without shrinkage:** they are mostly noise from small samples and schedule quirks; the signals we kept (injuries, own OL, pressure rates) are specific and tested.

### Agent tools
`get_edges(player or team, week)`, `get_injury_cascade(team)`, `get_buy_low_sell_high()`, `get_game_environment(game)`. The assistant must cite which adjustments drove its advice (type, size, source, confidence) and say when none applied; it presents cascades as context, not as projection changes.

## Recommendations v2: moves and trades (one engine for every screen)

Full design, diagnosis, backtests and limits: [docs/trade-engine-v2.md](docs/trade-engine-v2.md).

* **`season.py`** values everyone week by week: injury **return timelines** (news-derived games missed, else a status default, with uncertainty, a re-injury discount and a rust factor), byes, playoff weeks at 1.5x, edge-engine adjusted projections. Value is **signed points above replacement** plus **raw** rest-of-season points; nothing is clipped to 0, and bench players are ranked by raw + upside. A player in an IR slot costs no bench spot.
* **`market.py`** is *market value*: what other managers see (ESPN ADP, auction value, PPR draft rank, expert rest-of-season rank, % rostered/started), mapped onto the same scale as my value. **`acceptance.py`** answers "would he accept" from market fairness, need, situation, name value and that manager's history, as a label (likely / coin flip / unlikely) with the signals shown, never a made-up percentage. Logged negotiations ("confirmed by manager") override the estimate and update a per-manager tendency (Bayesian).
* **`trading.py`**: two separate answers per trade (should I offer it = my value; would they accept = market value + need + situation + history). The search scans the **whole league**, finds the **cheapest winning offer first** (1-for-1 before 2-for-1, no unneeded sweeteners), recomputes both lineups week by week including roster-spot costs and best actual free-agent fill-ins, and gives an **offer ladder** (Open / Fair / Walk away). Plain-English requests are parsed into explicit constraints you can correct. Large gaps between my model and the consensus are flagged *speculative*.
* **`moves.py`**: `evaluate_move()` / `find_moves()` used by the Players page, Overview, player sheet and the AI. A deterministic validation layer enforces **My strategy** (More > My strategy): streaming D/ST (and optionally K) ranked on this week's matchup with a minimum swap gain, position caps, never cutting a starter for a backup, recently-added protection, and a projection sanity check for one-week outliers. "No move needed" is a normal answer. `edge/dst.py` is the D/ST matchup model (validated out of sample).
* **`hub.py`** builds all of the above once per data refresh; `agent.py` only calls it (the assistant does no valuation of its own).

## Value model basics (`valuation.py`)

```
ppg = (games_played x actual_ppg + 4 x projected_ppg) / (games_played + 4)
```

`valuation.ValueModel` supplies the blended points per game and the league-measured replacement level per position (the first player *not* starting league-wide, from every team's solved best lineup under your real slot settings, so FLEX is split by who actually fills it). `season.py` builds everything else on top of it.

## The AI agent (`agent.py`)

By default the chat runs on **your Claude subscription**: it uses the Claude Agent SDK (`claude-agent-sdk`) through the
Claude Code app you're already logged into (check with `claude auth status`). No API key is needed, and Claude Code's
own file/shell tools are switched off so it can only call the league tools below. (`CHAT_BACKEND=api` switches to the
Anthropic API with a key.)

Claude (`ANTHROPIC_MODEL`, default `claude-sonnet-5-5`) is given these tools: `get_league_overview`, `get_my_roster`,
`get_team_roster`, `get_free_agents` (raw facts only), `find_moves`, `evaluate_move`, `evaluate_trade`, `find_trades`, `draft_trade_pitch`,
`log_negotiation`, `get_manager_profile`, `get_strategy`, `optimize_lineup`, `get_player_news`, `log_recommendation`. The system prompt forbids stating any number that didn't come from a tool, asks for
plain-English explanations, and requires every recommendation to end with "Do this in the ESPN app: ...". Teams can be
referenced by owner first name ("Kaden"). Recommendations are written to the `recommendations` table in
`data/fantasy_hub.db` (also viewable in the **Log** tab).

## Data & caching

* ESPN league data (via `espn-api`, wrapped in `league_client.py`) is cached in SQLite for `CACHE_TTL_SECONDS` (default 300).
  Use the sidebar **Refresh** button to bypass it.
* Sleeper's player list is cached 24h, trending lists 10 min, ESPN player news 15 min.
* The ESPN API is only ever *read*. Nothing in this repo can change a roster or send a trade.

## Tests

```bash
python -m pytest -q
```

Covers the season/market/acceptance models, trade search and moves rules, the lineup optimizer (including a brute-force optimality check), news alert logic, every API endpoint (FastAPI TestClient) and the agent loop (with a scripted fake Claude, so no API key is needed). The assistant's wording on tricky scenarios is a separate manual suite: `RUN_AGENT_SCENARIOS=1 python -m tests.agent_scenarios.run_live`. Backtests: `python -m tools.trade_backtest`, `python -m edge.dst`.

## Layout

```
server/           FastAPI app + serializers                   web/          React + Vite frontend (src/pages/*)
ctx.py            cached process-wide data + engines          fmt.py        small pure formatting helpers
assets.py         team brand + images                         ai_runner.py  runs the AI (subscription or API)
theme.py          saved theme preferences                     Makefile      setup / dev / start / test
league_client.py  the only espn-api importer                 valuation.py  value model + fairness
models.py         dataclasses used everywhere                trading.py    trade search + evaluator
config.py / db.py env config, SQLite cache, log, settings    moves.py      add/drop + streaming engine
season.py / market.py / acceptance.py / strategy.py / hub.py   v2 valuation, market value, acceptance, My strategy, shared bundle
sleeper.py        injuries + trending                        news.py       news feed + alerts
edge/             edge engine: history, modules, engine, backtest, news_ai, odds, forecast, timing
agent.py          Claude tool-use agent                      demo_data.py  fake league for tests/demo
optimizer.py      best lineup (Hungarian assignment)
```
