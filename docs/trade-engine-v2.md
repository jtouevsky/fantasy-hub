# Trade engine v2 and recommendation quality

Status: implemented. Section 1 (diagnosis) was written first, from live-league evidence, before any fixes; the rest describes what shipped.

## 1. Diagnosis

### 1a. Why the trade finder produced "A.J. Brown (IR) + Quinshon Judkins for Garrett Wilson, 61/39, unlikely to accept"

Reproduced on the live league (Week 5, 2026). The old model's numbers:

| Player | Slot / status | ppg (blended) | Games left | Availability | **Old "value"** |
|---|---|---|---|---|---|
| A.J. Brown (WR) | IR | 12.5 | 12 | 0.50 flat | **7.7** |
| Quinshon Judkins (RB) | RB starter | 13.7 | 12 | 1.00 | 30.2 |
| Garrett Wilson (WR) | WR starter | 15.0 | 12 | 1.00 | 44.6 |

`Brown-for-Wilson` straight up scored **85/15 for the other side, "Unlikely"**. Adding Judkins moved it to **56/44, "Maybe"**, which is the package the finder surfaced. In reality the other manager said he would do Brown-for-Wilson straight up.

Root causes, in the order they compound:

1. **One number plays two roles.** The same model value decides "is this good for me" and "would he accept". The acceptance label was `f(their share of MY model value, their lineup change)`. A trade can only look "fair" to the other manager if it also looks fair to my own model, so the tool could never say "he'd accept, but you shouldn't" or "great for you, he'll never take it".
2. **No market value.** Other managers do not use my model. ESPN's own data shows how they see these players: Brown has an average auction value of **25.4** vs Wilson's **23.3**, a PPR draft rank of **20** vs **29**, and an expert-consensus rest-of-season rank of **WR 10** (on IR!) vs **WR 18**. By market value Brown is *worth more* than Wilson, so a 1-for-1 is plainly plausible. My model never saw any of this.
3. **IR valuation is a flat discount.** `ROS_AVAILABILITY["INJURY_RESERVE"] = 0.5` multiplies every remaining game by 0.5 regardless of the return timeline, so a player out four weeks and a player out for the season are valued identically, and a healthy return in the playoffs (when it matters most) is not credited.
4. **Value is points above a high replacement level, clipped at 0.** Brown: (12.5 − 11.3) × 12 games × 0.5 = **7.7**. The replacement WR is 11.3 ppg (the best player the league *doesn't* start), so anyone near replacement gets a tiny or zero value. `max(0, …)` then turns every below-replacement player into exactly 0.0, which destroys ordering among bench players and made many different players look identical.
5. **The finder adds "sweeteners" to hit a *model-value* split.** A 1-for-1 that failed my 60/40 target (because Brown looked worthless) was extended with every possible extra player (`my_extras`), then ranked by closeness to the target split. Judkins was added only to push my own model's split toward 60/40; nothing about the other side required him. There was no "cheapest winning offer" search.
6. **Their lineup change was treated as a hard acceptance factor.** Trading for an IR player *lowers* their current lineup (Brown can't start), which the acceptance label punished (-3.0 pts/week), even though real managers regularly pay market price for injured stars.
7. **No roster-spot or hole accounting against actual free agents.** A 2-for-1 charged nothing for the roster spot the receiver must clear, and holes were filled with a generic replacement-level phantom, not the best player actually available in this league.
8. **Average points per week, not a schedule.** Lineup impact compared one smoothed number; it ignored byes, the return week of an injured player and the heavier weight of playoff weeks.

### 1b. Why the assistant's add/drop advice was bad

All four symptoms come from the move logic in `waivers.py` plus how the agent used it:

1. **"Add Patriots D/ST, drop Jonah Coleman" (just picked up a D/ST, and admitted the Patriots project lower this week).** `suggest_add_drops` treats D/ST like any position: it ranks by rest-of-season value and sums `ros_gain + weekly + depth`, so a *negative* this-week gain was outvoted by a rest-of-season number that is meaningless for a position you re-stream every week. There was no concept of a streaming position, no memory that I had just added a D/ST, and no cap on D/STs.
2. **"Add Kyler Murray (a 3rd QB, 7.2 ppg avg) by dropping an RB."** (a) No roster-construction rules: nothing capped QBs at 2, and the drop was chosen as the lowest-`ros_points` non-starter at *any* position (an RB), not a QB. (b) The candidate shortlist is seeded by `week_value` (this week's projection), so a single ESPN outlier (17.9 vs a 7.2 season average) lands at the top. There was no projection sanity check.
3. **"0.0 rest-of-season value" as a reason.** `ValueModel.value()` is `max(0, (ppg - replacement) * games * availability)`, so most of a roster is exactly 0.0. The agent quoted that number as if it meant something.
4. **Irrelevant facts (bench QB's bye).** `_player_row` returns `bye_week` for every player and the system prompt had no rule about relevance or length; the model reproduced whatever tool output it saw.
5. **The agent could choose moves on its own reasoning.** It had `get_free_agents` and `get_my_roster` and could (and did) assemble recommendations from raw lists, so the Waivers page and the assistant could disagree.

### 1c. Summary of root causes -> fixes

| Root cause | Fix in v2 |
|---|---|
| One value does two jobs | Two separate values (my value, market value) and two separate verdicts |
| No market value | Market value from ESPN ADP, auction value, PPR rank, consensus ROS rank, % rostered/started, quantile-mapped to the model scale |
| Flat IR discount | Return-timeline availability curve, IR-slot awareness |
| Clip to 0 | Signed points above replacement + raw ROS points; ranking by raw value + upside |
| Sweeteners / no search discipline | Cheapest-winning-offer search, offer ladder, whole-league scan |
| Acceptance blended with value | Separate acceptance model with named signals; negotiation log overrides |
| Average ppg, no schedule | Week-by-week optimal lineups for both teams (byes, return weeks, playoff weighting) |
| No roster rules / strategy | `strategy.py` settings: streaming, caps, drop logic, recently-added protection |
| Agent invents moves | One `find_moves()` / `evaluate_move()` used by every surface; validation layer; sanity checks; "no move" is valid |

## 2. Design

### 2a. Two questions, never blended

| Question | Driven by | Where |
|---|---|---|
| **Should I offer it?** | **My value**: change in my optimal starting lineup, week by week, rest of season (byes, return weeks, playoff weeks x1.5, adjusted projections, roster-spot cost, best actual free agent fills any hole) | `season.py`, `trading.evaluate` |
| **Would they accept it?** | **Their perception**: market value fairness (biggest signal), need fit, situation, name value, manager history | `market.py`, `acceptance.py` |

Both values are on the same "points above replacement" scale so the *gap* (my value minus market value) is the edge, and a 60/40 split means 60/40 in **my** value while market value is near even. Nothing is clipped to zero; a below-replacement player is negative, and bench ordering uses raw points plus upside.

### 2b. Injuries and IR

Availability by week is a normal-CDF return curve: news-derived games missed when known (tight spread), otherwise a status default (IR 6 games, Out 1.5, Suspended 3) with a wide spread, times a 0.92 re-injury discount and a rust factor (0.88 / 0.95 in the first two weeks back). Questionable counts for this week only (41% sit rate from nflverse history). A star on IR therefore keeps most of his market value but is valued by *when* he comes back, which matters most if it is in time for the playoffs. A player in an IR slot costs no bench spot.

### 2c. Market value

From ESPN's own fields for the user's league: average draft position, average auction value, PPR draft rank, expert consensus rest-of-season positional rank, % rostered and % started. Each is matched by rank/quantile onto the league's healthy points-above-replacement distribution (weights in `market.py`), then a consolidation premium (`CONSOLIDATION = 0.35`) makes one star worth more than two lesser players with the same points (scarcity curve). When ESPN has no market data for a player (rare), the model's healthy value is used and the row is marked as having no market.

### 2d. Acceptance

A logit of named signals: market fairness (scale 14), need fit (+-0.7 at 0.12 per point), situation, name/brand (+-0.6), manager history from the ESPN activity feed. Labels: *likely*, *coin flip*, *unlikely*. The signals and reasons are always shown; no percentage is displayed because none is calibrated. Logged negotiations override (`confirmed by manager`) only for the same ask or a strictly better/worse version of it, and also move a per-manager tendency (one Newton step of Bayesian logistic regression, prior variance 1, clipped at +-1.5) so a manager who keeps saying no or yes shifts later estimates. The override only touches *would they accept*; it never changes *should I offer it*.

### 2e. Search

For every other team (or one partner), every player I would want if he came free (adds >= 6 weighted points to my lineup) becomes a target, alone or in pairs. For each target I try give-sets smallest first: the core I named, then core + 1, then core + 2. As soon as a smaller offer clears acceptance, bigger ones are not tried, so a clearing 1-for-1 always beats a clearing 2-for-1. Trades that hurt my lineup are dropped unless I flagged sell/rebuild. Gains that rest on my model being far more bullish than the consensus are flagged *speculative* and count half in the ranking. Each result carries an offer ladder: **Open** (cheapest plausible), **Fair** (market-even for him), **Walk away** (the most I would give while still gaining >= 2).

### 2f. Moves, streaming and rules (`moves.py`, `strategy.py`)

`evaluate_move(add, drop)` re-solves my lineup with and without the move and then runs a deterministic validation layer; `find_moves()` is the only producer of recommendations (Players page, Overview, player sheet and the assistant call the same function):

* **Streaming** (D/ST on by default, K optional): ranked on *this week's* adjusted projection (for D/ST, ESPN's number blended 50/50 with the matchup model in `edge/dst.py`); swap only if the best option beats my current one by at least +2.0 (a bye or injury forces a swap), otherwise the answer is "keep your current D/ST". A short plan-ahead line shows next week's best matchup. No ping-pong: nobody I dropped in the last 7 days is re-added.
* **Caps**: at most 2 QBs (and no more than starters + 1), 1 D/ST, 1 K (0 if the league has no K slot), starters + 1 TE. Adding a player at a capped position requires dropping one at that position.
* **Drop logic**: redundancy first (the 3rd QB, the extra D/ST), then the least useful non-IR bench player by raw + upside. Never a starter-caliber player (starts >= 40% of remaining weeks) for a backup.
* **Recently added**: players added in the last 7 days (ESPN activity feed) are protected unless the gain is >= 5 pts and there is new injury news.
* **Projection sanity**: a one-week projection far above a player's own level, with no sourced reason (edge adjustments that explain >= 60% of the jump count as a reason), is *speculative*: the jump is cut to a third for the gain, the bar is +3 higher, confidence is capped at low.
* **Output**: at most 3 ranked moves with this-week gain, rest-of-season gain, a 1-2 line reason (Beginner mode adds one definition line), confidence, and "no move needed" when nothing clears the bar.

### 2g. Agent contract

The assistant has no valuation tools of its own. `find_moves`/`evaluate_move`/`find_trades`/`evaluate_trade` return the engine's result; the system prompt (with the strategy block, slots, caps, week) requires it to recommend only what they return, answer the two trade questions separately, quote labels instead of invented percentages, show the parsed constraints, and call `log_negotiation` when the user reports an answer. Player rows no longer contain placeholder values ("0.0 rest-of-season value") or irrelevant bye info.

## 3. How the original examples behave now

* **A.J. Brown (IR) for Garrett Wilson**: market value Brown 67.9 vs Wilson 59.2 (consensus ROS rank WR10 vs WR18), so he *receives* more by market; the label is "coin flip" with no sweetener. By my value it is still good for me (regression test `test_brown_for_wilson_regression_is_plausible_without_a_sweetener`). Note: the user does not want to make this trade; it is a calibration case only.
* **Just-added D/ST**: kept unless an alternative beats it by +2.0 this week (scenario `dst_just_added`); the held D/ST can never be re-proposed.
* **A third QB on one outlier projection**: blocked by the cap, never at the cost of an RB (scenario `two_qbs`).
* **"0.0 rest-of-season value"**: removed from tool output and from the UI; raw expected points are shown instead.

## 4. Validation: does the model-vs-market gap carry signal?

`python -m tools.trade_backtest` (offline; reproducible). Market proxy = FantasyPros expert-consensus positional ranks from nflverse's
`load_ff_rankings` (the snapshot nearest each season start; later snapshots are end-of-season, so this is a deliberately *stale* proxy for
how managers anchor on preseason reputation). Model = games-played blend (K=4) of actual ppg through week 4 with a prior from last season's
ppg, with **no ECR inside it**, so the two are independent. Decision week 5; outcome = actual points weeks 5-17. The market's expectation is
a per-position quadratic of ROS points on ECR rank, fit on 2024 only and applied unchanged to 2025.

| Season | n | corr(gap, ROS surprise) | Model-likes-more quintile vs market expectation | Model-likes-less quintile |
|---|---|---|---|---|
| 2024 (tune) | 124 | +0.12 | -5.7 pts (54% beat market) | -8.8 pts (60% underperformed) |
| 2025 (validate) | 125 | +0.30 | +24.5 pts (80% beat market) | -28.4 pts (72% underperformed) |

Reading: the gap points the right way in both years, but 2024 is within noise. So a model-vs-market gap is **a hint, not proof**: the engine
therefore (a) shows edge as a separate number from the market value, (b) flags very large gaps as *speculative*, and (c) never lets the gap
alone make a trade "likely". Terms of use: only nflverse's published data is used (offline, for this backtest); no KeepTradeCut/FantasyCalc or
other forbidden sources are scraped. Live market value uses ESPN's own fields from the user's league.
Limitations: ECR is preseason-only here, ~125 players per season, one decision week.

### 4b. D/ST matchup model (`python -m edge.dst`)

D/ST points under ESPN's default D/ST scoring (an assumption: the league's D/ST scoring items are not stored; sack 1, INT 2, fumble recovery 2, TD 6, safety 2, blocked kick 2, points-allowed bands) regressed (ridge) on the opponent's Vegas implied total, its trailing-4-game turnovers and sacks allowed, and wind. Trained on 2023-24 team-games, tested on 2025 (n = 544): MAE 3.83 vs 4.17 for "the defense's own trailing mean"; correlation with actual points 0.29 vs 0.08. Implied total has the largest effect (-0.41 pts per implied point). It is a matchup *estimate*, labelled as such, and blended 50/50 with ESPN's number.

### 4c. Blend constant

The games-played blend K = 4 (actual ppg vs projection) was re-checked in the v2 work and left unchanged; the market-gap backtest above uses the same K.

## 5. Verification

* `python -m pytest -q`: unit tests for IR valuation and slots, roster-spot cost, consolidation, cheapest-offer ordering (a clearing 1-for-1 beats a clearing 2-for-1), no sweeteners, position caps, streaming threshold, recently-added protection, no-zero-clipping ranking, the Brown-for-Wilson regression, the parser, the pitch helper, every page rendering in demo mode (AppTest), and the deterministic agent scenarios (`tests/agent_scenarios/`).
* Manual live-assistant suite (`RUN_AGENT_SCENARIOS=1 python -m tests.agent_scenarios.run_live`): the real assistant keeps the D/ST, declines a 3rd QB with the cap as the reason, labels a one-week spike speculative, and answers "no move needed". The first runs surfaced two real bugs, both fixed: the answer text could be lost when the model ended with only "I logged it", and a one-week spike was ranked #2 on face value.
* Live league (Week 5, 2026), headless and in the browser: all pages render; Trades finds whole-league options with both verdicts, week-by-week row, ladder; the chat input is dark in dark mode with the full placeholder visible.

## 6. Known limits

* **Market value is a proxy.** It comes from ESPN's own consensus fields. It does not see private league chatter, other managers' needs beyond roster composition, or recent trades unless they show up in the activity feed. The historical test of the model-vs-market gap is weak in 2024 and strong in 2025 (n ~ 125 each), so treat edge as a hint.
* **Large "+170" style gains** come from players my blended ppg rates far above the consensus (e.g. a hot start). They are flagged speculative and discounted in ranking but still shown; verify before proposing.
* **D/ST scoring** is assumed to be ESPN's default; if your league differs the matchup estimate shifts a little (ranking is mostly unaffected).
* **IR timelines** use news-derived games missed when the AI news scan has them, otherwise defaults (IR = 6 games); a wrong default moves a returning player's value.
* **Acceptance has no calibration data** until you log negotiations; it shows reasons and labels only. With a handful of logged answers the per-manager tendency is intentionally small.
* **No data for in-season weekly ECR history** exists in nflverse (only a preseason and end-of-season snapshot per year), so the backtest compares the model at week 5 with the preseason consensus; it measures the *direction* of the gap, not an exact tradable price.
* The manual agent suite depends on the model's wording and a logged-in Claude; it can flake and is intentionally not part of the normal test run.
* Nothing here sends anything: trades, claims and messages are drafted for the user to do in ESPN.
