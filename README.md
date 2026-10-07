# Fantasy Hub

A personal, **read-only** team-manager for an ESPN fantasy football league: dashboard, lineup optimizer,
waiver suggestions, trade analyzer/finder, news, and an AI chat agent. It never changes your roster -
every recommendation ends with something for you to do by hand in the ESPN app.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit .env (it is git-ignored)
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
streamlit run app.py
```

No credentials yet? Click **Use demo data** on the first screen to explore with a fake league.

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
* **Brand data by stable IDs** - NFL names, abbreviations, colors and logos come from ESPN's public team directory (cached 30 days); headshots come from ESPN's CDN by ESPN player id. Every image URL is verified once server-side, so a missing photo or logo becomes initials instead of a broken image. Defenses use team logos.
* **Materials** - light glass (nav, chips), medium glass (floating panels, inputs, AI/offer cards), near-solid surfaces for dense rosters and tables. Solid fallbacks apply automatically for `prefers-reduced-transparency` or browsers without `backdrop-filter`.
* **Type** - Geist (UI), Barlow Semi Condensed (scores, team and player names), tabular numerals for every score and projection, Geist Mono only for the AI tool trace. Fonts load from Google Fonts; offline it falls back to system fonts.
* **Motion** - 140 / 220 / 380 ms tiers, one easing curve, press feedback on buttons, everything disabled under `prefers-reduced-motion`.
* **Responsive** - on phones the nav becomes an icon-only bottom bar and rows/scoreboards restack.
* Source: `static/theme.css` (tokens + components), `theme.py`, `ui.py`, `assets.py`.

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

## How the player value model works (`valuation.py`)

```
ppg          = (games_played x actual_ppg + 4 x projected_ppg) / (games_played + 4)
games_left   = weeks from now to the end of the fantasy season, minus the NFL bye if it is still ahead
availability = ACTIVE 1.0 | QUESTIONABLE 0.97 | DOUBTFUL 0.85 | OUT 0.75 | INJURY_RESERVE 0.5
ros_points   = ppg x games_left x availability
value        = max(0, ppg - replacement_ppg[position]) x games_left x availability
```

* **ppg** blends what the player has actually done with ESPN's projection (the projection counts as 4 games of evidence), so
  one hot or cold week does not swing the number.
* **replacement_ppg[position]** is the points-per-game of the first player *not* starting league-wide at that position, from
  all rostered players plus the top free agents. "How many start" is **measured**, not assumed: every team's best lineup is
  solved using your league's real slot settings, so FLEX slots are split between RB/WR/TE by who actually fills them.
  This is what builds in **positional scarcity**: a position where starters are far better than the free-agent pool
  (and few are available) produces a high `value` for its stars.
* **value** is "rest-of-season points above a free pickup". Players at or below replacement are worth 0.

### Trade fairness

```
package_value = best player's value + 0.6 x (each additional player's value)     # 2-for-1s aren't a simple sum
split         = my_get_value / (my_get_value + my_give_value)                    # 60 means I receive 60% of the value
```

`evaluate_trade` also re-solves **both** teams' best lineups before and after the trade (holes are filled by a free
replacement-level pickup, since you could grab one on waivers), and reports who starts/sits and the weekly points change.

### Trade finder (`trades.py`)

Given a target team, the player you're offering, and a target split, it searches 1-for-1, 2-for-1 (you add a sweetener) and
1-for-2 packages, and ranks them with:

```
score = 100 - 3 x |my_split - target|
        + 4 x (their lineup improvement, up to 4 pts/wk)      or  - 10 x (their lineup loss)
        + 4 x (my lineup change, capped at +/-4 pts/wk)
        - 6 x (my_split - 65)  if my_split > 65                 # so lopsided the other manager would obviously refuse
        - 20                    if the other manager's acceptance is "Unlikely"
```

So deals that fill a need on **their** roster outrank deals that only look good on paper. All knobs are constants at the
top of `trades.py`.

### Waivers (`waivers.py`)

Each (add, drop) pair is scored by re-solving **your** lineup with and without the move (this week and rest of season), so
positional need, bye/injury coverage and bench depth are captured automatically. The drop is always one of your weakest
non-starters.

## The AI agent (`agent.py`)

By default the chat runs on **your Claude subscription**: it uses the Claude Agent SDK (`claude-agent-sdk`) through the
Claude Code app you're already logged into (check with `claude auth status`). No API key is needed, and Claude Code's
own file/shell tools are switched off so it can only call the league tools below. (`CHAT_BACKEND=api` switches to the
Anthropic API with a key.)

Claude (`ANTHROPIC_MODEL`, default `claude-sonnet-5-5`) is given these tools: `get_league_overview`, `get_my_roster`,
`get_team_roster`, `get_free_agents`, `evaluate_trade`, `find_trades`, `optimize_lineup`, `suggest_waiver_moves`,
`get_player_news`, `log_recommendation`. The system prompt forbids stating any number that didn't come from a tool, asks for
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

Covers the value model and fairness math, the lineup optimizer (including a brute-force optimality check), waiver and trade
ranking, news alert logic, and the agent loop (with a scripted fake Claude, so no API key is needed).

## Layout

```
app.py            shell: theme, header, search, nav          view_*.py     one module per page
ctx.py            per-session data + cross-page actions      dialogs.py    player sheet + AI sheet
ui.py             HTML components (rows, scoreboard, chart)  assets.py     team brand + verified images
theme.py / static/theme.css  design tokens + styles          ai_runner.py  runs the AI (subscription or API)
league_client.py  the only espn-api importer                 valuation.py  value model + fairness
models.py         dataclasses used everywhere                trades.py     evaluator + finder
config.py / db.py env config, SQLite cache, log, settings    waivers.py    add/drop suggestions
sleeper.py        injuries + trending                        news.py       news feed + alerts
edge/             edge engine: history, modules, engine, backtest, news_ai, odds, forecast, timing
agent.py          Claude tool-use agent                      demo_data.py  fake league for tests/demo
optimizer.py      best lineup (Hungarian assignment)
```
