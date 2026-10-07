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
