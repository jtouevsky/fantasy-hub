# Edge engine backtest

_Generated 2026-10-07 01:56 by `python -m edge.backtest` in 210s._

## Method

* **Target:** actual weekly fantasy points in *this league's* scoring (PPR 1.0, 4-pt pass TD, 6-pt rush/rec TD, -2 INT/fumble lost, 0.04 pass / 0.1 rush-rec yd), computed from nflverse box-score stats (`nflreadpy`).
* **Baseline:** trailing 4-game average of fantasy points (2+ prior games). ESPN's historical weekly projections aren't available, so each module is measured on its **incremental** improvement over this simple baseline. Real ESPN projections are better than this baseline, so true gains over ESPN will be smaller.
* **Population:** QB/RB/WR/TE who played, baseline >= 3 pts (includes backups who could be added off waivers), weeks 3-18. 2024: 3,638 player-games, 2025: 3,690. Pre-game information only (injury report status, Vegas closing lines, actual wind/temperature as a forecast proxy).
* **No tuning on reported data:** coefficients fit on 2024 weeks 3-10; strength (alpha) chosen on 2024 weeks 11-18; refit on all 2024; **2025 is the held-out season shown below.** ON/SHRUNK/OFF decisions use the 2025 result on the rows each module moves, so treat the final 2025 numbers as validation of the shipped configuration, not as an unbiased estimate of future gains.
* **Cap:** total adjustment per player-week <= 35% of max(baseline, 6 pts).
* MAE = mean absolute error in fantasy points (lower is better). 'Gain' = baseline MAE minus adjusted MAE (positive = better), with a paired-bootstrap 95% CI.

## Results by module (2025 hold-out)

| Module | Decision | alpha | Rows moved | MAE on moved rows: base → adj | Gain on moved rows (95% CI) | Gain on all rows |
|---|---|---|---|---|---|---|
| Game environment (Vegas) | **ON** | 0.25 | 779 of 3690 | 6.36 → 6.33 | +0.025 (+0.008 to +0.043) | +0.0057 (+0.0017 to +0.0094) |
| Weather | **ON** | 1 | 288 of 3690 | 5.74 → 5.45 | +0.292 (+0.036 to +0.590) | +0.0223 (-0.0009 to +0.0449) |
| Injury cascade (vacated opportunity) | **OFF** | 0 | 724 of 5193 | 5.37 → 5.42 | -0.046 (-0.105 to +0.009) | -0.0094 (-0.0176 to -0.0015) |
| Opposing defense injuries & pass rush | **ON** | 1 | 1955 of 3690 | 5.90 → 5.73 | +0.169 (+0.114 to +0.220) | +0.0931 (+0.0665 to +0.1220) |
| Opportunity vs. production + role trend | **ON** | 1 | 3064 of 3690 | 5.79 → 5.57 | +0.220 (+0.162 to +0.282) | +0.1826 (+0.1323 to +0.2309) |

### Notes per module

* **Game environment (Vegas)** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.017 over 698 rows.
* **Weather** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.762 over 206 rows.
* **Injury cascade (vacated opportunity)** - 2025 hold-out: worse than baseline on the rows it moves. 2024 (in-sample) gain on moved rows: -0.005 over 852 rows.
* **Opposing defense injuries & pass rush** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.162 over 2029 rows.
* **Opportunity vs. production + role trend** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.225 over 3081 rows.

### Big movers (|adjustment| >= 2 pts), 2025

* **Game environment (Vegas)**: only 0 rows that large - not enough to evaluate
* **Weather**: 141 rows; gain +0.37 pts MAE (95% CI -0.14 to +0.89)
* **Injury cascade (vacated opportunity)**: 24 rows; gain +0.58 pts MAE (95% CI -0.28 to +1.46)
* **Opposing defense injuries & pass rush**: 166 rows; gain +0.41 pts MAE (95% CI -0.01 to +0.86)
* **Opportunity vs. production + role trend**: 798 rows; gain +0.60 pts MAE (95% CI +0.40 to +0.78)

## Where each module's gain comes from (feature ablation, fit on 2024, 2025 hold-out, full strength)

**Defense**

| Signal alone | MAE | Gain vs baseline (95% CI) |
|---|---|---|
| Own OL injuries | 5.536 | +0.0940 (+0.0690 to +0.1213) |
| Opposing DB (CB/S) injuries | 5.611 | +0.0192 (+0.0070 to +0.0306) |
| Opposing pass-rusher injuries | 5.618 | +0.0129 (+0.0070 to +0.0189) |
| Pass rush vs. protection (play-by-play pressure) | 5.630 | +0.0001 (-0.0064 to +0.0062) |

**Regression**

| Signal alone | MAE | Gain vs baseline (95% CI) |
|---|---|---|
| xFP gap (buy low / sell high) | 5.479 | +0.1515 (+0.0984 to +0.2021) |
| Snap-share trend (role growing) | 5.610 | +0.0202 (+0.0047 to +0.0371) |

## Injury cascade diagnostics (why it ships as context, not a projection change)

The cascade estimates how a confirmed-out player's carries/targets are redistributed (with/without history shrunk toward position-flow rates). It points the right way in its core case but did **not** improve weekly accuracy over a player's recent form under any filter we tried, so it is shown as context and is **not** added to projections.

**Core case**: teammates of a confirmed-Out starter (>=30% of carries or >=15% of targets), unscaled estimate vs. what happened (2024-25):

| Position | Rows | Mean predicted | Mean actual vs baseline | Slope | Corr |
|---|---|---|---|---|---|
| RB | 256 | +1.49 | +1.10 | 0.71 | 0.18 |
| WR | 415 | +1.36 | +0.95 | 0.53 | 0.06 |
| TE | 184 | +1.04 | +1.13 | 0.54 | 0.03 |

True backups (baseline < 6, predicted >= +1): 184 rows, predicted +2.10, actual +3.17 vs baseline.

**Conviction filters** (min share of the absent player, min probability he's out): chosen on 2024, checked on 2025:

| Min share | Min p(out) | 2024 validation (n, gain) | 2025 hold-out (n, gain, 95% CI) |
|---|---|---|---|
| 0.08 | 0.0 | 142, +0.093 | 724, -0.043 (-0.105 to +0.014) |
| 0.08 | 0.9 | 290, +0.044 | 620, -0.028 (-0.102 to +0.046) |
| 0.15 | 0.0 | 183, +0.078 | 668, -0.055 (-0.126 to +0.017) |
| 0.15 | 0.9 | 269, +0.021 | 496, -0.037 (-0.133 to +0.061) |
| 0.25 | 0.0 | 184, +0.039 | 360, +0.018 (-0.102 to +0.125) |
| 0.25 | 0.9 | 166, -0.041 | 260, +0.005 (-0.148 to +0.153) |

**Size deadbands** (only apply estimates >= T points; scale fit on 2024):

| T | 2024 rows | fitted scale | 2024 gain | 2025 rows | 2025 gain (95% CI) |
|---|---|---|---|---|---|
| 0.5 | 930 | 0.46 | -0.028 | 796 | -0.042 (-0.100 to +0.012) |
| 1.0 | 482 | 0.44 | -0.032 | 412 | -0.053 (-0.152 to +0.042) |
| 2.0 | 154 | 0.49 | -0.039 | 145 | -0.008 (-0.277 to +0.262) |
| 3.0 | 68 | 0.40 | -0.149 | 49 | +0.235 (-0.310 to +0.793) |
| 4.0 | 31 | 0.16 | -0.011 | 27 | +0.239 (-0.096 to +0.577) |

## Do the trade/waiver tags predict the next game? (2025)

Mean of (actual - baseline) in the *following* game for players carrying each tag. Positive = they out-scored their baseline.

| Tag | Player-games | Mean next-game residual (95% CI) |
|---|---|---|
| All players (reference) | 3,690 | -0.60 (-0.86 to -0.38) |
| Buy low (xFP exceeds production by >= 3 pts/game) | 294 | +2.10 (+1.20 to +3.02) |
| Sell high (production exceeds xFP by >= 3 pts/game) | 410 | -4.01 (-4.79 to -3.23) |
| Role growing (snap share +8 pts over last 2 games) | 892 | -0.22 (-0.74 to +0.26) |

## Live strengths (judgment, not measured)

ESPN projections already absorb part of each signal and are far better than the trailing-average baseline used here, so live strengths are discounted:

| Module | Backtest alpha | Live multiplier | Why |
|---|---|---|---|
| Game environment (Vegas) | 0.25 | x0.5 | ESPN projections already reflect game environment |
| Weather | 1 | x1 | ESPN rarely adjusts for wind/cold |
| Injury cascade (vacated opportunity) | 0 | x0.75 | ESPN adjusts for confirmed injuries but lags on depth shifts (already shrunk twice: fitted scale x validated alpha) |
| Opposing defense injuries & pass rush | 1 | x0.75 | mostly OL injuries, which ESPN does not model |
| Opportunity vs. production + role trend | 1 | x0.5 | ESPN's projections already use opportunity (a trailing average does not) |

## All shipped modules together (2025 hold-out)

* 3,690 player-games. MAE **5.630 → 5.372** (gain +0.2588, 95% CI +0.1974 to +0.3214).

| Position | Baseline MAE | With edges |
|---|---|---|
| QB | 7.092 | 6.776 |
| RB | 5.819 | 5.463 |
| WR | 5.339 | 5.164 |
| TE | 4.903 | 4.639 |

## Cap sensitivity (all shipped modules, 2025 hold-out)

The per-player cap bounds how far edges can move a projection. Smaller = safer, larger = lets big opportunity changes through.

| Cap (of max(baseline, floor)) | Floor | MAE with edges | Gain vs baseline |
|---|---|---|---|
| 20% | 6 | 5.379 | +0.2517 |
| 35% | 0 | 5.369 | +0.2617 |
| 35% | 6 | 5.372 | +0.2588 |
| 50% | 6 | 5.380 | +0.2507 |
| 75% | 6 | 5.382 | +0.2486 |
| 1000% | 6 | 5.384 | +0.2467 |

## Caveats

* Weather uses actual game-time wind/temperature as a stand-in for a forecast; live forecasts are noisier, so expect a smaller effect. Precipitation isn't in the historical table and is untested.
* News scanning (module 6) and timing (module 7) can't be backtested - there is no historical news feed. They only feed modules 1-2 and alerts; they never create point adjustments by themselves.
* One baseline, two seasons, one league's scoring. Small effects (< ~0.05 pts MAE) are within noise even when positive.

## Stability-weighted value (volume vs touchdowns)

`python -m edge.stable` (fits on 2024, validates on 2025; 2023 only supplies history). Source: nflverse `ff_opportunity` (expected receptions, yards, interceptions and expected TDs by pass/rush/receiving, from the quality of every target and carry) plus actual weekly stats, scored with **this league's scoring** (reception 1, pass TD 4, rush/rec TD 6, 0.04/0.1 yards).

**Method.** Each player-game's points are split into *volume points* (yards, receptions, turnovers) and *touchdown points*. For the last 8 games (g = games available, at least 3):

```
stable_ppg = (g x vol_actual + kv x vol_expected)/(g + kv)  +  (g x td_actual + ktd x td_expected)/(g + ktd)
```

kv and ktd are chosen by grid search on 2024 to minimize next-game squared error: **kv = 8, ktd = 10**. The grid is flat near the optimum (MSE 48.1 at the best cell vs 49.2 for raw trailing points), and the data does not support regressing volume much more *lightly* than touchdowns: both are pulled about half-way to expectation at 8 games, and TDs are regressed at least as hard as volume. A **TD-dependent** player (scoring >= 8 ppg with >= 40% of it from TDs on fewer than 9 touches+targets per game) takes an extra fitted penalty (-2.11 pts/game, shrunk by sample size).

**Does it predict better?** Comparators: trailing 8-game points per game and trailing 4-game points per game (the baseline the edge engine uses). ESPN's historical projections are not available from any free source, so they cannot be a comparator here; the live app still starts from ESPN's projection and uses this as the "actual" side of the blend.

| Test | Season | n | Raw 8-game ppg | Raw 4-game ppg | **Stability-weighted** |
|---|---|---|---|---|---|
| Next-game MAE (pts) | 2024 (tune) | 4,211 | 5.363 | 5.502 | **5.314** |
| Next-game MAE (pts) | 2025 (validate) | 4,258 | 5.384 | 5.496 | **5.308** |
| Next-game rank correlation (weekly, Spearman) | 2024 | | 0.545 | | **0.554** |
| Next-game rank correlation | 2025 | | 0.536 | | **0.548** |
| Rest-of-season ppg MAE, decision week 5 | 2024 | 210 | 4.15 | | **4.00** |
| Rest-of-season ppg MAE, decision week 5 | 2025 | 224 | 3.96 | | **3.73** |
| Rest-of-season rank correlation (actual weeks 5-17 points) | 2024 | 210 | 0.565 | | **0.567** |
| Rest-of-season rank correlation | 2025 | 224 | 0.634 | | **0.652** |

The overall gain is small but consistent in both seasons (about 1.4% lower next-game error, 6% lower rest-of-season ppg error in 2025): most players are not TD flukes, so most estimates barely move. The effect is concentrated where it should be:

**Same trailing points, different sources** (RB/WR/TE averaging 8-16 ppg over their last 8 games):

| Season | Group | n | Trailing ppg | Next-game ppg (actual) | Model's estimate |
|---|---|---|---|---|---|
| 2024 | TD-fueled, < 9 touches+targets | 24 | 10.04 | **4.87** | 8.74 |
| 2024 | Volume-backed, >= 9 touches+targets, <= 20% TDs | 241 | 12.34 | **12.56** | 12.81 |
| 2025 | TD-fueled | 28 | 10.05 | **5.79** | 8.70 |
| 2025 | Volume-backed | 200 | 11.73 | **12.12** | 12.31 |

TD-fueled receivers/backs lose about half their points the next game; volume-backed players hold. The regression alone moves the TD-fueled group's estimate only part of the way (8.7 vs 4.9-5.8 actual), so the explicit TD-dependent penalty exists: fit on 2024 it cuts the flagged group's 2025 error from 5.12 to 4.63 MAE (n = 32) without hurting anyone else (overall MAE 5.308 vs 5.304).

**Floor / median / ceiling.** Multipliers on the player's projection are the 20th / 50th / 80th percentiles of (actual / pre-game estimate), by position and by TD-dependence bucket (low < 25% / mid / high >= 40% of points from TDs). Fit on 2024, checked on 2025: 22% of outcomes fell below the 20th percentile and 17% above the 80th (target 20 / 20; n = 3,814), so the bands are reasonably calibrated, slightly too high on the ceiling side.

Limits: the sample of clearly TD-fueled players is small (n = 24-32 per year), so the penalty is shrunk; red-zone and goal-line touches are shown but not yet a model input; route participation is not in free nflverse data (shown as unavailable); kickers and defenses have no stability profile.
