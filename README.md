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
| `ANTHROPIC_API_KEY` | From console.anthropic.com (only needed for the AI chat tab). |
| `ANTHROPIC_MODEL` | Defaults to `claude-sonnet-5-5`. |

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

| Tab | What it does |
|---|---|
| **Dashboard** | Your roster (projected/actual points), this week's matchup, standings, injury & bye report. |
| **Lineup** | Optimal starting lineup vs your current one, with the projected gain of each swap. |
| **Waivers** | Free agents ranked by rest-of-season and this-week value, Sleeper trending/breakout flags, and concrete "add X, drop Y, +Z pts/week" moves. |
| **Trades** | *Find me a trade* (target team + the player you're offering + a target split like 60/40) or *evaluate* a specific deal. |
| **News** | ESPN player news + Sleeper injury data for your roster and your opponent's, with alerts that should change your lineup. |
| **AI Chat** | Ask Claude things in plain English. It uses the same tools as the tabs and never makes up numbers. |
| **Log** | Every recommendation the agent made, so you can mark later whether it was good. |

Everything is **read-only**. Each recommendation ends with what to do in the ESPN app.

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
app.py            Streamlit UI (all tabs)           optimizer.py   best lineup (Hungarian assignment)
league_client.py  the only espn-api importer        valuation.py   value model + fairness
models.py         dataclasses used everywhere       trades.py      evaluator + finder
config.py / db.py env config, SQLite cache + log    waivers.py     add/drop suggestions
sleeper.py        injuries + trending               news.py        news feed + alerts
agent.py          Claude tool-use agent             demo_data.py   fake league for tests/demo
```
