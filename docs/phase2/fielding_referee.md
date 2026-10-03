# Phase 2 row 10: the fielding referee (audit, then results)

Branch `phase2/fielding`. Tool: `tgs-viz/backtest/referee_fielding.py`. Tests: `tgs-viz/tools/tests/test_referee_fielding.py`.
Companion document for row 2 (the out values): `docs/phase2/out_values.md`.

## 1. What this means for you

The engine now has a check of its fielding range curves against a real league season. Before this, the only check was `fielding_curves_fit.py`'s gate (the curves must stay within 3 runs of the clone sims they were fitted on, `:309`), which cannot see a curve that is wrong for the live league.

The curves hold up where there is enough data and show one weak spot. On the two league-seasons played under the current game engine (BLM 2058 and SSB 2043), the infield curves (1B, 2B, SS) track real results within noise, pooled slope 0.92 to 0.97 (1.00 = the curve moves runs exactly as fast as the real league did). The left-field (LF) curve is about twice as steep as the real league in both: pooled slope 0.53 with a standard error (SE) of 0.11, 4.1 SEs below 1.00. At the left-field rating gap 50 to 70, the engine credits 23.6 runs per 1200-inning position slot; the two samples imply about 12.5.

Nothing is changed. The two-sample governance rule (a curve moves only when the same departure shows up in two independent samples, and then by a shrunk amount) says "replicated" for LF, but a third sample (BLM 2057) disagrees and was played under a different chance flow (section 5). My recommendation is to flag LF, not to move it, and re-run after BLM's next season.

This tool cannot test the out values (H38 / H39). The slope is the same whatever out value is used, because the model and the observed runs are both multiplied by it (verified by test). Row 2 handles that.

## 2. Audit: every input traced

Tags: 🟢 computed from our real data, 🟡 borrowed constant, 🔵 deliberate assumption.

### Model side (what the tool scores)

| Input | Source | Tag | Notes |
|---|---|---|---|
| range-to-plays curve per position (knots, `m2`, `offset`) | `engine/calib/BLM/fielding_curves.json`, from `fielding_curves_fit.py` | 🟢 | isotonic (monotone) fit on BLM clone-sim archive; `offset` transported so the live population's innings-weighted mean is 0. Sim data is not on this machine, so the curves are read, not refit. |
| chances per 1200 innings, `T5 T8 T12 T15 T18 T22 T26` | Data Points of `The Sheets BLM/The Sheet Hitters.xlsx` (via `hitters.scan_consts`) | 🟢 | equal to `metadata-latest.json` M5.. and to `extracted/BLM_hitters_datapoints.json` (checked, 0 numeric differences in 411 cells) |
| out value `H38` (infield), `H39` (outfield) | same workbook, 0.75 / 0.90 | 🟡 | hand-entered; cancels in the slope (section 4, check 5) |
| ratings `IF RNG`, `IF ARM`, `OF RNG`, `HT` | `Fielding_Ratings.csv` (BLM live); `ratings_history.db` pull (2057); `fielding_ratings.csv` (SSB) | 🟢 | BLM live pull equals Fielding_Ratings exactly (546 of 546 players, all three columns). Ratings are the scouted values the engine prices with, treated as true: 🔵 (section 6, flag 3). |
| sheet linear cells (`--linear`) | `P9 L9 Q9 M9 K9 ...` in the same workbook | 🟢 | pre-curve branch of `hitters.compute`, kept for comparison |

### Observed side

| Input | Source | Tag | Notes |
|---|---|---|---|
| chances (Plays A) and made (Plays M) per player-position | `Fielding_Data` BIZ columns: chances = BIZ-R+L+E+U+Z+I, made = BIZ-Rm+Lm+Em+Um+Zm | 🟢 | same definition as `metadata_calibrate.fielding_tables`. The 2057 actuals use `opps_0..5` and `opps_made_0..5`. |
| innings | `IP` in x.y notation, y = outs | 🟢 | `ip_thirds`; 2057 uses `ip + ipf/3` |
| league made rate, league chances per 1200 innings | sums over all players at the position in the sample | 🟢 | equal to metadata M6.. and M5.. for BLM 2058 (observed `pa_obs` = `pa_model` to 4 digits) |
| observed range runs `y = (made/chances - league rate) x chances-per-1200 x out value` | computed | 🟢 | runs per 1200-inning position slot |
| minimum 20 chances per player | | 🔵 | inherited from the dashboard referee |
| elite band: range rating >= 68 and >= 300 innings | | 🟡 | inherited from the dashboard referee, not re-derived |
| bootstrap: 4000 resamples, seed 20261003 | | 🔵 | |

### The statistic

Chance-weighted least squares (WLS) of `y` on the engine's range channel `x = pm_pw(pos) x T x out value`, one regression per position. Standard errors per coefficient are the largest of: HC1 (heteroskedasticity-robust, scaled by n/(n-2)), a cluster bootstrap over players, and the binomial floor (the SE that independent sampling noise in each player's made count alone would produce). "Unfitted skill" is how much of the observed spread the channel explains with no refit, centring both on their weighted means. "Dispersion" is the residual variance over the binomial variance (1.00 means sampling noise only).

## 3. Port notes (what differs from the dashboard's referee)

The dashboard's `model/tools/referee_fielding.py` reads dashboard internals (`src.hitters`, response factors, scout/OSA blend). Kept: the observed definition, WLS, the three-way SE rule, the elite band, the governance rule. Changed:

- The channel is the engine's: `pm_pw` curve (or the sheet linear cells), times `T`, times `H38` / `H39`. There is no response factor in this engine (ours has `FIELDING_RESPONSE_FACTORS_27`).
- Ratings are read as given (one set per pull). The dashboard blends 0.9 scout + 0.1 OSA (a second ratings view); his data has one.
- The bootstrap is vectorised: all 4000 resamples are evaluated at once from a multiplicity matrix, resampling whole players (clusters).
- Added: a rung table (residual by 5-point rating rung), the dispersion statistic, `--linear` comparison, a chance-flow regime check, and the two-sample verdict as a function (`two_sample_verdict`) instead of prose.
- Loaders: his `metadata_calibrate` loaders for the live CSVs, OOTP actuals for banked seasons, the dashboard's `fielding_data_<pos>.csv` layout for SSB.

## 4. Verification (all run this session)

1. Channel equals the engine. `test_referee_fielding.EngineParity` runs `hitters.compute()` for 400 BLM hitters with the error, double-play and arm terms zeroed so `RunsP = pmaa x H38 (or H39)`, and compares to the referee's channel at every position, curve branch and linear branch: equal to 1e-9. (14 subtests.)
2. Vectorised interpolation equals `hitters._interp_knots` (test).
3. WLS equals `numpy.polyfit` with weights; HC1 equals a hand-rolled sandwich loop; the vectorised cluster bootstrap equals a per-resample loop on the same draws (tests).
4. A frozen 14-player shortstop fixture (`tools/tests/fixtures/referee_fielding/`) is built so the true slope is exactly 1.2 (made = 10000 x (0.72 + 1.2 x engine rate)); the tool returns slope 1.200000000, intercept `-1.2 x mean(model)`, R2 1.000, unfitted skill `1 - 0.04/1.44`.
5. Out-value invariance: with `H38` 0.75 vs 0.50 the slope is identical and the intercept scales by 0.5/0.75 (test).
6. The BLM live observed table reproduces metadata: chances per 1200 innings equals the `T` cell and league made rate equals M6/M9/M13/M16/M19/M23/M27, for all seven positions.
7. Pricing basis of SSB: running `ingest/ratings.run_hitters` on `public/data/SSB/hitters.json` with the BLM calibration reproduces the shipped file with max difference 0.0 in `Max WAA wtd` over 6866 players; with the TGS calibration the difference is 2.54. So SSB is priced on BLM's curves and Data Points, and `--basis BLM` is the right way to referee it.

Not verified: the clone-sim archive that the curves were fitted on is not on this machine, so I could not check the curves' sim-side fit or refit anything.

## 5. Results

Units: slope is dimensionless; intercepts are runs per 1200-inning slot. n is players with at least 20 chances. "chances" is the sum of their chances.

### BLM 2058 (live: `Fielding_Data` + `Fielding_Ratings`, ratings pull of 2058-10-01), priced on BLM's piecewise curves

| pos | n | chances | slope | SE | z vs 1 | intercept | R2w | unfitted skill | dispersion | linear-cell skill |
|---|---|---|---|---|---|---|---|---|---|---|
| 1B | 77 | 9890 | 1.155 | 0.377 | +0.4 | +0.19 | 0.121 | 0.12 | 1.46 | 0.15 |
| 2B | 97 | 17043 | 0.956 | 0.104 | -0.4 | +0.06 | 0.495 | 0.49 | 0.95 | 0.49 |
| 3B | 92 | 15193 | 1.313 | 0.148 | +2.1 | -0.18 | 0.432 | 0.41 | 1.39 | 0.39 |
| SS | 93 | 18485 | 0.819 | 0.118 | -1.5 | +0.34 | 0.351 | 0.33 | 1.40 | 0.28 |
| LF | 102 | 15735 | 0.523 | 0.155 | -3.1 | +0.69 | 0.093 | 0.02 | 1.16 | 0.07 |
| CF | 83 | 18308 | 0.929 | 0.220 | -0.3 | -0.13 | 0.308 | 0.31 | 1.31 | 0.19 |
| RF | 100 | 16392 | 1.371 | 0.217 | +1.7 | +0.40 | 0.254 | 0.24 | 1.30 | 0.18 |

### SSB 2043 (OOTP 27; `--sample dir:... --basis BLM`), priced on BLM's curves as the fork does

| pos | n | chances | slope | SE | z vs 1 | intercept | R2w | unfitted skill | dispersion |
|---|---|---|---|---|---|---|---|---|---|
| 1B | 74 | 9159 | 0.797 | 0.277 | -0.7 | +0.60 | 0.132 | 0.12 | 0.86 |
| 2B | 90 | 16178 | 0.992 | 0.122 | -0.1 | +0.99 | 0.388 | 0.39 | 1.53 |
| 3B | 89 | 14271 | 0.932 | 0.186 | -0.4 | +1.53 | 0.313 | 0.31 | 1.45 |
| SS | 96 | 17383 | 1.117 | 0.116 | +1.0 | +5.47 | 0.501 | 0.50 | 1.20 |
| LF | 94 | 15162 | 0.535 | 0.168 | -2.8 | +1.22 | 0.105 | 0.03 | 1.08 |
| CF | 84 | 16968 | 0.661 | 0.166 | -2.0 | +1.10 | 0.176 | 0.13 | 1.49 |
| RF | 104 | 15298 | 0.890 | 0.254 | -0.4 | +1.46 | 0.115 | 0.11 | 1.55 |

The SSB intercepts are population shifts, not a test: the curves' `offset` zeroes the mean of BLM's live population, and SSB's shortstops average -4.5 runs per slot on the channel (BLM's average +0.4), so the fitted line sits +5.5 above zero at the BLM mean.

### BLM 2057 (OOTP actuals + ratings pull 4 of 2057-10-13; heights from the live ratings), priced on BLM's curves

| pos | n | chances | slope | SE | z vs 1 | intercept | R2w | unfitted skill | dispersion | linear-cell skill |
|---|---|---|---|---|---|---|---|---|---|---|
| 1B | 52 | 8198 | 1.414 | 0.340 | +1.2 | +0.30 | 0.278 | 0.25 | 1.05 | 0.19 |
| 2B | 103 | 20041 | 1.375 | 0.158 | +2.4 | -1.75 | 0.491 | 0.45 | 1.49 | 0.46 |
| 3B | 82 | 12416 | 0.746 | 0.207 | -1.2 | -0.85 | 0.200 | 0.18 | 1.38 | 0.18 |
| SS | 88 | 22116 | 1.180 | 0.135 | +1.3 | +0.44 | 0.503 | 0.49 | 1.28 | 0.54 |
| LF | 99 | 13346 | 0.986 | 0.139 | -0.1 | +0.80 | 0.366 | 0.37 | 1.00 | 0.30 |
| CF | 93 | 19469 | 1.224 | 0.197 | +1.1 | +2.90 | 0.338 | 0.33 | 1.24 | 0.35 |
| RF | 89 | 14864 | 1.179 | 0.318 | +0.6 | -0.56 | 0.258 | 0.25 | 1.18 | 0.20 |

Ratings pull 3 (2057-10-02) and pull 5 (2057-12-31) move individual slopes by up to 0.09 (CF 1.224 to 1.075 at pull 5) and change no conclusion.

### The 2057 sample is a different chance-flow regime

Observed chances per 1200 innings divided by the engine's `T` cell:

| pos | BLM 2058 | SSB 2043 | BLM 2057 |
|---|---|---|---|
| 1B | 1.000 | 0.986 | 0.966 |
| 2B | 1.000 | 1.017 | 1.175 |
| 3B | 1.000 | 0.997 | 0.821 |
| SS | 1.000 | 1.006 | 1.199 |
| LF | 1.000 | 1.033 | 0.857 |
| CF | 1.000 | 0.985 | 1.057 |
| RF | 1.000 | 0.991 | 0.905 |

BLM 2058 and SSB 2043 (OOTP 27) flow the same way to within 3.3% at every position. BLM 2057 moves 2B and SS up by 18% to 20% and 3B and LF down by 14% to 18%, with the same league-wide total. I do not know why (inferred: a different game engine or zone geometry in 2057; the fork's STATUS.md calls BLM's calibration "the OOTP 27 one", and `ratings_history.db` has no engine tag). The tool prints a regime warning whenever any position is off by more than 10%. Consequence: BLM 2057 is not a clean second sample for curves fitted on the current engine. SSB 2043 is.

### Two-sample governance, the clean pair (BLM 2058 vs SSB 2043)

| pos | z live | z SSB | pooled slope | z pooled | verdict |
|---|---|---|---|---|---|
| 1B | +0.4 | -0.7 | 0.923 ± 0.223 | -0.3 | consistent with 1 |
| 2B | -0.4 | -0.1 | 0.971 ± 0.079 | -0.4 | consistent with 1 |
| 3B | +2.1 | -0.4 | 1.165 ± 0.116 | +1.4 | watch |
| SS | -1.5 | +1.0 | 0.970 ± 0.083 | -0.4 | consistent with 1 |
| LF | -3.1 | -2.8 | 0.528 ± 0.114 | -4.1 | replicated |
| CF | -0.3 | -2.0 | 0.758 ± 0.133 | -1.8 | watch |
| RF | +1.7 | -0.4 | 1.169 ± 0.165 | +1.0 | consistent with 1 |

For comparison, BLM 2058 vs BLM 2057 gives LF "watch" (pooled 0.780 ± 0.103) and 2B "watch" (the 2057 slope 1.375 is 2.4 SEs high, the 2058 slope is 0.4 SEs low). Across all three samples the LF slopes (0.523, 0.986, 0.535) are heterogeneous: Cochran's Q = 6.5 on 2 degrees of freedom, p about 0.04 (hand computation, not in the tool).

### What this says about the curves

- Infield: no sign of a curve error. 2B and SS pooled slopes 0.97; 1B is too noisy to say (SE 0.22 to 0.38; the engine's 1B range curve moves runs by only 1.2 per slot between ratings 50 and 70). 3B is the one infield position whose two clean samples disagree (1.31 and 0.93) with no consistent direction.
- Left field: both OOTP 27 samples say the curve is about half as steep as reality. Engine gap 50 to 70 range is 23.6 runs per slot; implied by BLM 2058 is 12.3, by SSB 2043 is 12.6, by BLM 2057 is 23.2. The rung residuals in both clean samples go from positive at ratings 40 to 55 (low-rated left fielders do better than the line) to negative at 70 and above.
- Center field: the high end looks over-credited. The residual at rating 75 is -13.4 runs per slot (BLM 2058, 6 players, beyond 2 SEs) and -15.4 (SSB, 7 players, beyond 2 SEs), -22.4 (BLM 2057, 4 players); at rating 60 it is -17.9, -22.4, -11.6. Elite-band means (range >= 68, >= 300 innings) do not show it (model +9.4, observed +12.7 in BLM 2058), so this is a mid-curve shape signal, not a level signal.
- Curves versus the sheet's linear cells, same data: unfitted skill is higher for the curves in 7 of 14 position-samples, lower in 5, equal in 2; the mean difference is +0.02. The one large gain is BLM 2058 CF (0.31 vs 0.19). The real league cannot confirm the sim finding that the linear cells are wrong by 4 to 14 runs in the tails, because the tails hold 0 to 6 players per rung; it does not contradict it either.
- Slopes below 1 are partly expected. Scouted ratings carry measurement error, which pulls a regression slope toward 0 (errors-in-variables). I have no measured reliability for BLM's fielding ratings, so I cannot say how much of 0.53 is attenuation. LF has the lowest R2 (0.09 to 0.10) in both clean samples, which fits a channel with a flat response plus noisy ratings.
- Count of slopes beyond 2 SEs: 5 of 21 (LF live, LF SSB, CF SSB, 3B live, 2B 2057); about 1 would be expected by chance at 5%.

## 6. Flags and how each is resolved

1. Dashboard referee ratings blend (0.9 scout + 0.1 OSA) is absent from his data. Resolved: the engine prices with one ratings set, so the referee uses the same.
2. BLM 2057 chance flow differs from 2058 and SSB. Resolved by reporting it as a regime warning and treating the clean pair as BLM 2058 plus SSB 2043. Cause not determined.
3. Rating measurement error attenuates slopes. Not resolved: needs a reliability estimate for BLM's fielding ratings (second ratings view, or repeated pulls within a season). Slopes in this document are the raw ratings-on-outcomes slopes.
4. Players in both BLM samples overlap (54% to 66% of each position's qualified players appear in both), so 2058 vs 2057 is not independent. SSB 2043 is a separate league.
5. Selection: managers choose who plays a position, so a rung may hold players who are better or worse than their rating suggests. Not controlled.
6. Heights for the 2057 first basemen come from 2058 ratings; 12 of 64 qualified first basemen had no 2058 row and were dropped (reported as `n_unmatched`).
7. The curves' `offset` is fitted to the 2058 population, so intercepts for other samples are shifts, not evidence.
8. Single-season SEs are wide: 0.10 to 0.38 on slopes. A curve error smaller than about 30% at one position cannot be seen in one season.

## 7. Decisions for you

1. Do not move any curve now. Options: (a) leave all curves; (b) flag LF and CF in the app's notes; (c) refit LF with a flatter response. I recommend (a) and (b): the LF signal is replicated in the clean pair but a third sample disagrees, and one more BLM season would settle it.
2. Wire the referee into the post-season flow (for example after `Bank Season`). It reads only; it needs the pandas interpreter. I did not edit `tools/tasks.py` or any bat. Say if you want it.
3. Add a ratings-reliability measurement for fielding so the slopes can be de-attenuated. Needs two scouting views of the same players; not on disk.

## 8. Reproduce

```
PY=/path/to/python-with-pandas
$PY tgs-viz/backtest/referee_fielding.py --league BLM --db <ratings_history.db> \
    --sample live --sample actuals:2057:4
$PY tgs-viz/backtest/referee_fielding.py --league BLM --sample live \
    --sample dir:<ootp-dashboard>/leagues/SSB/metadata/2043          # BLM 2058 vs SSB 2043 verdicts
$PY tgs-viz/backtest/referee_fielding.py --league SSB --basis BLM --sample dir:<...>/2043
$PY tgs-viz/backtest/referee_fielding.py --league BLM --linear          # sheet linear cells
$PY -m pytest tgs-viz/tools/tests/test_referee_fielding.py -q
```

`ratings_history.db` is gitignored; pass `--db` (the main checkout holds it) or set `RATINGS_ARCHIVE_ROOT`.
