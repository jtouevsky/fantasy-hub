# Edge engine backtest

_Generated 2026-10-07 00:37 by `python -m edge.backtest` in 1s._

## Method

* **Target:** actual weekly fantasy points in *this league's* scoring (PPR 1.0, 4-pt pass TD, 6-pt rush/rec TD, -2 INT/fumble lost, 0.04 pass / 0.1 rush-rec yd), computed from nflverse box-score stats (`nflreadpy`).
* **Baseline:** trailing 4-game average of fantasy points (2+ prior games). ESPN's historical weekly projections aren't available, so each module is measured on its **incremental** improvement over this simple baseline. Real ESPN projections are better than this baseline, so true gains over ESPN will be smaller.
* **Population:** QB/RB/WR/TE who played, baseline >= 5 pts, weeks 3-18. 2024: 2,945 player-games, 2025: 2,971. Pre-game information only (injury report status, Vegas closing lines, actual wind/temperature as a forecast proxy).
* **No tuning on reported data:** coefficients fit on 2024 weeks 3-10; strength (alpha) chosen on 2024 weeks 11-18; refit on all 2024; **2025 is the held-out season shown below.** ON/SHRUNK/OFF decisions use the 2025 result on the rows each module moves, so treat the final 2025 numbers as validation of the shipped configuration, not as an unbiased estimate of future gains.
* **Cap:** total adjustment per player-week <= 35% of max(baseline, 6 pts).
* MAE = mean absolute error in fantasy points (lower is better). 'Gain' = baseline MAE minus adjusted MAE (positive = better), with a paired-bootstrap 95% CI.

## Results by module (2025 hold-out)

| Module | Decision | alpha | Rows moved | MAE on moved rows: base → adj | Gain on moved rows (95% CI) | Gain on all rows |
|---|---|---|---|---|---|---|
| Game environment (Vegas) | **ON** | 0.25 | 771 of 2971 | 6.50 → 6.47 | +0.028 (+0.009 to +0.047) | +0.0072 (+0.0021 to +0.0125) |
| Weather | **ON** | 0.75 | 231 of 2971 | 6.15 → 5.86 | +0.287 (+0.012 to +0.573) | +0.0232 (+0.0011 to +0.0453) |

### Notes per module

* **Game environment (Vegas)** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.017 over 682 rows.
* **Weather** - 2025 hold-out improvement is statistically clear (CI excludes 0). 2024 (in-sample) gain on moved rows: +0.837 over 173 rows.

## All shipped modules together (2025 hold-out)

* 2,971 player-games. MAE **6.068 → 6.039** (gain +0.0292, 95% CI +0.0056 to +0.0530).

| Position | Baseline MAE | With edges |
|---|---|---|
| QB | 7.149 | 7.092 |
| RB | 6.193 | 6.150 |
| WR | 5.763 | 5.737 |
| TE | 5.515 | 5.526 |

## Caveats

* Weather uses actual game-time wind/temperature as a stand-in for a forecast; live forecasts are noisier, so expect a smaller effect. Precipitation isn't in the historical table and is untested.
* News scanning (module 6) and timing (module 7) can't be backtested - there is no historical news feed. They only feed modules 1-2 and alerts; they never create point adjustments by themselves.
* One baseline, two seasons, one league's scoring. Small effects (< ~0.05 pts MAE) are within noise even when positive.
