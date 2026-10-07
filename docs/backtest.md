# Edge engine backtest

_Generated 2026-10-07 01:03 by `python -m edge.backtest` in 136s._

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
| Injury cascade (vacated opportunity) | **ON** | 0.5 | 972 of 3690 | 5.80 → 5.76 | +0.044 (+0.002 to +0.084) | +0.0118 (+0.0012 to +0.0218) |
| Opposing defense injuries & pass rush | **ON** | 1 | 1955 of 3690 | 5.90 → 5.73 | +0.169 (+0.114 to +0.220) | +0.0931 (+0.0665 to +0.1220) |
| Opportunity vs. production + role trend | **ON** | 1 | 3064 of 3690 | 5.79 → 5.57 | +0.220 (+0.162 to +0.282) | +0.1826 (+0.1323 to +0.2309) |

### Notes per module

* **Game environment (Vegas)** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.017 over 698 rows.
* **Weather** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.762 over 206 rows.
* **Injury cascade (vacated opportunity)** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.043 over 1069 rows.
* **Opposing defense injuries & pass rush** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.162 over 2029 rows.
* **Opportunity vs. production + role trend** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.225 over 3081 rows.

### Big movers (|adjustment| >= 2 pts), 2025

* **Game environment (Vegas)**: only 0 rows that large - not enough to evaluate
* **Weather**: 141 rows; gain +0.37 pts MAE (95% CI -0.14 to +0.89)
* **Injury cascade (vacated opportunity)**: 20 rows; gain +0.50 pts MAE (95% CI -0.51 to +1.37)
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
| Injury cascade (vacated opportunity) | 0.5 | x0.5 | ESPN adjusts for confirmed injuries but lags on depth shifts |
| Opposing defense injuries & pass rush | 1 | x0.75 | mostly OL injuries, which ESPN does not model |
| Opportunity vs. production + role trend | 1 | x0.5 | ESPN's projections already use opportunity (a trailing average does not) |

## All shipped modules together (2025 hold-out)

* 3,690 player-games. MAE **5.630 → 5.362** (gain +0.2686, 95% CI +0.2048 to +0.3324).

| Position | Baseline MAE | With edges |
|---|---|---|
| QB | 7.092 | 6.776 |
| RB | 5.819 | 5.436 |
| WR | 5.339 | 5.164 |
| TE | 4.903 | 4.624 |

## Cap sensitivity (all shipped modules, 2025 hold-out)

The per-player cap bounds how far edges can move a projection. Smaller = safer, larger = lets big opportunity changes through.

| Cap (of max(baseline, floor)) | Floor | MAE with edges | Gain vs baseline |
|---|---|---|---|
| 20% | 6 | 5.373 | +0.2575 |
| 35% | 0 | 5.359 | +0.2714 |
| 35% | 6 | 5.362 | +0.2686 |
| 50% | 6 | 5.369 | +0.2611 |
| 75% | 6 | 5.372 | +0.2583 |
| 1000% | 6 | 5.374 | +0.2563 |

## Caveats

* Weather uses actual game-time wind/temperature as a stand-in for a forecast; live forecasts are noisier, so expect a smaller effect. Precipitation isn't in the historical table and is untested.
* News scanning (module 6) and timing (module 7) can't be backtested - there is no historical news feed. They only feed modules 1-2 and alerts; they never create point adjustments by themselves.
* One baseline, two seasons, one league's scoring. Small effects (< ~0.05 pts MAE) are within noise even when positive.
