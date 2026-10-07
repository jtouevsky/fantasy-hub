# Trade engine v2 and recommendation quality

Status: design + diagnosis (this section was written first, from live-league evidence, before any fixes).
Sections "Design", "Validation" and "Known limits" are filled in below as each piece lands.

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
