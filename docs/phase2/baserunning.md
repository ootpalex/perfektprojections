# Phase 2, row 6: baserunning audit (SBA%, SB%, UBR)

Branch `phase2/baserunning`, worktree head `43ed272` (his engine as forked), ours audited at `8c6337a`
(ootp-dashboard `main`). Nothing in the fork's engine was changed. Reproduce every number below with
`python docs/phase2/baserunning_audit.py` (read-only, no network; about 40 seconds).

## 1. What this means for you

1. **Our UBR line is the form his bug B9 condemned, and it is wrong in our pipeline.** `model/src/hitters.py:342`
   computes `ubr_poly - lg.ubr`. `lg.ubr` is negative, so every hitter gets about +0.6 runs per 600 plate
   appearances (PA) more UBR than the fork's engine gives the same player. Against real seasons it lands
   at +0.24 runs/600 PA (BLM 2058) and +0.30 (SSB 2043) when the real league mean is -0.28 and -0.35.
   The effect is 0.05 to 0.06 wins per hitter per 600 PA at the fork's runs-per-win of 10.036. It is uniform
   across hitters, so it moves hitters against pitchers and against replacement level, not hitters against each other.
2. **The fork's UBR sign is right for reproducing the observed level, but it is a choice of frame, not a
   finding.** His `+C40` form predicts a league mean of -0.37 runs/600 PA (BLM 2058) against a real -0.28.
   A frame centred on the league average (cubic only, no C40 term) predicts -0.09. Which one is "right"
   depends on whether WAA (wins above average) should be measured from the league's observed UBR level or from zero.
   His stolen-base term (wSB) is already centred at zero, so the centred frame would make baserunning
   (BSR = wSB + UBR) internally consistent. This is decision D1 in section 7.
3. **Our OOTP-26 stolen-base-attempt intercept (`c0` = +0.0091) is sign-wrong on every real league I could test**:
   BLM 2058 and SSB 2043 (OOTP 27), and TGS 2044 (OOTP 26). With it, projected league attempts run
   +31%, +33% and (for the 26 linear model) +52% above the real count. Our OOTP-27 path already
   replaces it (`metadata.py:809`), so this is fixed for SSB. The 26 path is untouched and the fix
   cannot reach it (section 4.2).
4. **Do not port our league-adaptive SBA intercept into his engine.** His engine already reproduces the
   league attempt rate to within 2.4% on the two OOTP-27 seasons (BLM 2058 -2.4%, SSB 2043 -0.4%) and fits
   the shape across steal-rating buckets better than ours does (summed bucket error 22% and 27% of attempts,
   against 35% and 36% for our adaptive version). Porting would move his level by +0.004 (BLM) to +0.023 (TGS)
   and would worsen TGS bucket error from 14.9% to 16.2% (section 5).
5. **Ours under-projects elite base-stealers.** In the STE 75+ bucket (23 hitters in each of BLM 2058 and
   SSB 2043) real wSB is +4.76 and +5.12 runs/600 PA; his engine gives +5.59 and +6.10; ours gives +3.51 and +3.80.
   Ours is 1.3 runs low, his is 0.8 to 1.0 high. This is the flat-slope problem the OOTP-27 audit logged as F2.

## 2. Terms used here

- **STE, RUN, SPE** are the Steal, Running and Speed ratings, display scale 20 to 80.
- **SBA%** is stolen-base attempt rate: (SB + CS) / (1B + BB + HBP). The denominator is "opportunities": the times a
  hitter reached first base by single, walk or hit-by-pitch. **SB%** is SB / (SB + CS).
- **UBR** is OOTP's ultimate base running, exported only as a per-player season total. **UBR rate** is
  UBR / base opportunities, where base opportunities = (1B + BB + HBP) x 3 + 2B x 2 + 3B x 2 - SB - 3 x CS
  (his `calibrate.py:174`). Our `_shared.py:204` and the runtime formulas in both codebases (his `hitters.py:289`, our `hitters.py:371`) use
  3B x 1 instead. This changes the league rate by 0.5% (BLM 2058: -0.000608 versus -0.000611) and is inherited from
  the Excel sheet. It is not a finding.
- **C39, C40, C41** are his workbook's live league constants: pooled SB%, pooled UBR rate and pooled SBA%.
  **H8, H9** are the league's PA-weighted mean STE and RUN. **H35, H36** are the run value of a caught stealing and
  the league wSB per opportunity. Ours are `lg.sb_pct`, `lg.ubr`, `lg.sba_rate`, `avg_steal`, `avg_bsr`.
- **Pooled** means summed over the league (total SB + CS over total opportunities), so high-attempt players dominate it.
- **Wired** means committed into production; **gated** means built but off pending your decision.
- **Bucket SE** is a player-resample bootstrap standard error (400 resamples).

## 3. Inputs, traced (🟢 computed from real data, 🟡 borrowed constant, 🔵 deliberate assumption)

### His engine (`tgs-viz/engine/hitters.py:259-300`, fit in `calibrate.py:245-257`)

| Input | Value (BLM) | Tag | Provenance and check |
|---|---|---|---|
| SBA line `B15 + C15 x (min(STE,80) - H8)` | -0.1084 + 0.01441 x (STE - 48.47) | 🟢 | Fitted by weighted least squares on STE >= 55 hitters in the BLM clone-sim archive as a deviation from the archive pooled rate (`calibrate.py:250`, fix B1). Sim data not on this machine; the fit cannot be re-run here. |
| `C41` (live pooled SBA%) | 0.09865 | 🟢 | Re-derived: BLM 2058 `Hitting_Data` gives 4227 attempts / 42,847 opportunities = 0.09865. Matches the workbook cell to 5 digits. |
| `H8` (mean STE) | 48.4724 | 🟢 | Re-derived from `Batter_Ratings`: identical to our `avg_steal` (48.47237680590109). |
| SB% line and `C39` | -0.1175 + 0.00807 x (STE - H8); 0.7715 | 🟢 | `C39` re-derived: ΣSB / Σ(SB+CS) = 0.77147. Line is a sim fit. |
| SB% cap 0.888 | `SB_CAP` (`hitters.py:94`) | 🟢 | Measured from the clone archive (career SB% by STE bucket); not re-derivable here. Real data are consistent: STE 80+ bucket is 0.854 (n = 4). |
| STE and RUN input clamp at 80 | `hitters.py:268-272` | 🔵 | Support ends at 80 in the calibration. Real 2058 BLM: 2 hitters above STE 80, 19 above RUN 80. |
| UBR line `B19 + C19 x (min(RUN,80) - H9)` | 2.08e-5 + 2.601e-4 x (RUN - 53.50) | 🟢 | Sim fit as a deviation from the archive pooled rate (`calibrate.py:257`). |
| `C40` (live pooled UBR rate) | -0.000611 | 🟢 | Re-derived: BLM 2058 UBR -85.1 over base opportunities gives -0.000611 (3B x 1 definition). |
| SB weight 0.2 | hard-coded | 🟡 | Sheet constant, not equal to the league's own SB run value. Ours hard-codes it too (`hitters.py:364`). Held equal for both sides in the comparisons below. |
| `H35`, `H36` | -0.3918, 0.006471 | 🟢 | Workbook values from the BLM metadata. |

### Ours (`model/src/hitters.py:333-342`, `regressions.py:517-545`, `data_points.py:206-232`, `metadata.py:809-863`)

| Input | Value | Tag | Provenance and check |
|---|---|---|---|
| OOTP-27 SBA curve (knots 37/55/72, slopes 0.00076/0.00182/0.00642/0.01172) | `data_points.py:572` | 🟢 | Fit on designed test-league sims (H-pool), referee-checked on SSB 2043. Sims not on this machine. |
| SBA `c0`, OOTP 26 canonical | +0.009117 | 🟡 | Calibration value from a "quiet bell" sim substrate. Found wrong in section 4.2. |
| SBA `c0`, OOTP 27 adaptive | -0.02225 (BLM 2058), -0.02405 (SSB 2043) | 🟢 | `-E_w[pw(STE)]` over the league's PA-weighted STE distribution. Re-derived by calling our `_compute_ste_pa_distribution` and `piecewise_delta` on each league's files. |
| `lg.sba_rate`, `lg.sb_pct` | 0.09865 / 0.7715 (BLM); 0.10030 / 0.7624 (SSB) | 🟢 | Pooled, same as his `C41`, `C39` for BLM. |
| SB% curve and `c0` = -0.1332 | `data_points.py:584` | 🟡 | Canonical 26 intercept kept on the 27 path; the 2026-07-02 audit judged it conservative (about 30% too negative). Not changed here. |
| UBR slope 0.00019 (27), 0.000152 (26) | `data_points.py:593` | 🟢 | Sim fit. Section 4.1 compares it with real slopes. |
| UBR `c0` = +3.09e-5 | `data_points.py:229` | 🟢 | The centred regression (`regressions.py:853`, `_compute_linear_as_cubic`) returns the deviation intercept from the league mean, which is about 0. The CLAUDE.md note that baserunning `c0` is "a real offset, not zero" applies to SBA and SB%, which are convex in the rating. It does not apply to UBR, which is nearly linear. |
| `lg.ubr` | -0.000611 (BLM), -0.000751 (SSB) | 🟢 | Pooled UBR / base opportunities, re-derived. |
| `- lg.ubr` in the UBR line | `hitters.py:342` | 🔵 | Inherited from the Excel sheet; see 4.1. |

## 4. Findings

### 4.1 Is `hitters.py:342` the `(cubic − C40)` form? Yes (verified by running).

The mechanism. Both pipelines fit UBR rate on RUN as a deviation from the league. Ours calls
`_compute_linear_as_cubic`, which centres the outcome (`regressions.py:517-540`), then pins `c0` to +3.09e-5. His
`calibrate.py:257` fits `y - GT` the same way. The intercept is therefore about 0 relative to a level of
-6e-4 to -7e-4 per base opportunity, so the cubic is a deviation, not a rate.

The sheet's original formula (`The Sheet Hitters.xlsx`, `UBR vR`) is `(SUMPRODUCT(cubic) - 'Data Points'!$C$40) x bases`. That
is correct only when `B19` holds a raw rate (about equal to C40), because subtracting C40 then centres the result.
Both of our pipelines and his refit changed `B19` to a deviation and kept the minus. His B9 fix flips it to `+C40`.
Ours kept `- lg.ubr`.

League mean UBR, runs per 600 PA (predicted total over all hitters in the file, divided by their PA):

| Season (population) | Real | Fork as built (`cubic + C40`) | Cubic only | Fork cubic `− C40` | Ours (`hitters.py:342`) |
|---|---|---|---|---|---|
| BLM 2058 (547 matched hitters) | -0.28 | -0.37 | -0.09 | +0.19 | +0.24 |
| SSB 2043 (490 matched hitters) | -0.35 | -0.20 (BLM C40) | +0.08 | +0.36 | +0.30 |
| BLM 2057, 2058 constants (547 hitters) | -0.75 | -0.43 | -0.16 | +0.12 | +0.19 |

Ours minus the fork's engine is +0.61, +0.51 and +0.62 runs/600 PA in the three rows, which is the B9 effect
the audit estimated at "+0.5 to +1.0". The sign of `lg.ubr` is negative in every season I measured, so
`ubr_poly - lg.ubr` adds a phantom of |lg.ubr| x base opportunities in all of them.

By RUN bucket (BLM 2058, UBR per base opportunity x 1000; boot SE in brackets) the level error is the same size in every bucket:

| RUN | n | Real | Fork as built | Cubic only | Cubic −C40 | Ours |
|---|---|---|---|---|---|---|
| < 40 | 164 | -6.87 (0.41) | -7.57 | -6.96 | -6.35 | -4.46 |
| 40-49 | 57 | -2.66 (0.68) | -3.45 | -2.84 | -2.23 | -1.45 |
| 50-59 | 75 | -0.59 (0.78) | -0.89 | -0.28 | +0.33 | +0.42 |
| 60-69 | 95 | +1.50 (0.55) | +1.81 | +2.42 | +3.03 | +2.39 |
| 70+ | 156 | +4.80 (0.40) | +5.04 | +5.65 | +6.26 | +4.87 |

(SSB 2043 and BLM 2057 tables are in the script output.) Slopes: the real WLS slope of UBR rate on RUN is
2.38e-4 +- 1.1e-5 (BLM 2058), 2.58e-4 +- 1.2e-5 (SSB 2043), 1.42e-4 +- 1.2e-5 (BLM 2057). His wired slope is
2.60e-4; ours is 1.90e-4 (27) and 1.52e-4 (26). The seasons disagree with each other by more than their own SEs, so one
season cannot choose; two of three favour his. Ours matches the top bucket (4.87 versus 4.80) only because its
too-flat slope is offset by the phantom add.

Unresolved flag (D1): the data fix the sign. They do not fix the frame (observed level versus zero-centred).

### 4.2 Our OOTP-26 SBA `c0` = +0.0091 is sign-wrong: confirmed (verified by running).

Check: the average-rated hitter's real attempt rate sits well below the pooled rate, so `c0` (average-rated minus pooled) must be negative.

| Population | Pooled SBA% | STE 45-54 real (SE) | Ours with canonical `c0` | Ours with adaptive `c0` | League attempts error, canonical |
|---|---|---|---|---|---|
| BLM 2058 (OOTP 27) | 0.0987 | 0.0561 (0.0039) | 0.1066 | 0.0752 | +31.1% |
| SSB 2043 (OOTP 27) | 0.1003 | 0.0543 (0.0053) | 0.1076 | 0.0744 | +33.2% |
| BLM 2057, 2058 constants | 0.1025 | 0.0570 (0.0044) | 0.1063 | 0.0749 | +24.7% |
| TGS 2044 (OOTP 26, linear model) | 0.1123 | 0.0528 | 0.1007 | not defined (see below) | +51.7% |

Real gap, average-rated bucket minus pooled: -0.043 (BLM), -0.046 (SSB), -0.059 (TGS). The adaptive intercept
(-0.022, -0.024) restores the league total (-0.7% and +0.1%) but only halves the bucket gap, because the
wired slope is too flat (section 4.3).

For OOTP 26 the adaptive formula returns 0. The 26 SBA model is linear, and `-E_w[c1 x (STE - avg)]` is exactly 0
when `avg` is the same weighted mean. So the sign error cannot be fixed by the mechanism ours used for 27. On TGS the
linear model also meets the floor at 0 attempts for low STE, which pushes the clipped mean up; setting `c0` = 0 still
leaves +46% (0.1642 versus 0.1123). That the 26 path is wrong is verified; what to do about 26 is outside this row.

### 4.3 Does his C41 handling scale with the run environment, and should ours be ported? No port.

His SBA rate is `C41 + (-0.1084 + 0.01441 x (STE - H8))`, floored at 0 per hitter. The live pooled rate `C41` is added; the
fitted deviation is a fixed absolute offset. Ours is `lg.sba_rate + pw(STE) - E_w[pw]`: the same additive structure with a
mean-preserving offset. Neither multiplies by the environment.

| Check | His engine | Ours (27, adaptive) |
|---|---|---|
| League attempts error, BLM 2058 | -2.4% | -0.7% |
| League attempts error, SSB 2043 (BLM constants) | -0.4% | +0.1% |
| League attempts error, BLM 2057 (2058 constants) | -9.9% | -5.9% |
| Sum of absolute bucket errors / real attempts, BLM 2058 | 22.4% | 34.8% |
| Same, SSB 2043 | 26.7% | 36.0% |
| Same, BLM 2057 | 21.1% | 37.8% |
| wSB, STE 75+, runs/600 PA, real +4.76 (BLM) / +5.12 (SSB) / +6.51 (BLM 2057) | +5.59 / +6.10 / +5.80 | +3.51 / +3.80 / +3.74 |

His line predicts 0.0000 for STE below 45 (real 0.8% to 2.8%) and 0.007 for STE 45-54 (real 5.6%); ours over-predicts the same
buckets (0.046 to 0.075). His STE 65-74 bucket runs high (0.253 versus 0.214), ours runs low (0.164). The low-STE misses cost
little: the wSB term is floored at zero, so both sides give -0.9 runs/600 PA against a real -0.85 to -1.20.

Does the additive `C41` transport across run environments? Test: TGS 2044's pooled rate (0.1123) is 13.8% above BLM 2058's (0.0987).
Swapping the fitted lines between leagues, with each league's own pooled rate and `H8` substituted:

| Data | Native line | Swapped line |
|---|---|---|
| TGS 2044 | -12.0% league, 14.9% bucket | -10.5% league, 14.0% bucket |
| BLM 2058 | -2.4% league, 22.4% bucket | -6.6% league, 16.9% bucket |

The league error moves by 1.5 and 4.2 points. The TGS -12% miss survives swapping, so it belongs to the clipped linear shape, not to the
environment handling. (TGS is OOTP 26 and BLM is OOTP 27, so this mixes two engines; treat it as supporting, not conclusive.)

What a mean-preserving constant would do to his engine (solve for the constant so the opportunity-weighted mean of
`max(line + c, 0)` equals the pooled rate): BLM 2058 +0.1029 versus the built 0.0987; SSB 2043 +0.0993 (against
BLM's built 0.0987); BLM 2057 +0.1178; TGS 2044 +0.1381 versus the built 0.1149. Bucket error moves from 22.4% to 24.1% (BLM) and
from 14.9% to 16.2% (TGS), so the level fix trades shape for level.

### 4.4 Other flags and how each resolves

| Flag | Evidence | Resolution |
|---|---|---|
| Ours has no clamp at STE/RUN 80; his clamps both | BLM 2058: 2 hitters STE > 80, 19 RUN > 80. SSB 2043: 1 and 27 (STE max 95). Real RUN 80+ UBR rate 6.63e-3 / 6.78e-3 against his 6.30e-3 and ours 5.99e-3 / 5.88e-3. Our SBA at STE 90 is 0.41 (his cap 0.445; real STE 80+ n = 4: 0.54 and 0.66) | No action. The clamps change fewer than 30 players and the real data do not show distortion. |
| Our SB% overshoots at the top and undershoots at the bottom | STE 75+: real 0.856 / 0.833, his 0.872 / 0.874, ours 0.884 / 0.875. League SB% in SSB: real 0.762, his 0.783, ours 0.779 | Both overshoot SSB by about 2 points. The fork prices SSB on BLM's `C39` (0.7715). Recorded; no change. |
| SSB priced on BLM constants | SSB pooled SBA% is 0.1003 against BLM's `C41` 0.0987; SSB UBR rate -0.000751 against BLM's `C40` -0.000611 | SBA effect under 2%. UBR effect is 0.06 runs/600 PA (SSB 2043 under his cubic: error +0.14 with BLM's C40, +0.08 with SSB's own). Recorded; no change. |
| BLM 2057 weaker than 2058 on RUN and UBR | Top-bucket UBR rate +1.65e-3 against +4.80e-3; slope 1.42e-4 against 2.38e-4. Ratings are from the 2057-10-13 pull | Seasonal variation or a rating-scale event (STATUS notes a pull 4 to 5 scale event). Used as an out-of-time check only. |
| Scout-rating noise | Production uses scouted ratings, as do these files, so real slopes are attenuated by scout error | The comparisons are made in the frame production uses. A true-rating fit would be steeper for both sides. |

## 5. Gated options (nothing is applied)

- `docs/phase2/baserunning_ubr_centered.patch` removes `+ g("C40")` from `hitters.py:289` (the centred frame). `git apply --check` passes.
  Effect if applied: every hitter's UBR rises by |C40| x bases, +0.28 runs/600 PA at BLM's C40 (-0.088 versus -0.368 league mean),
  +0.03 wins per hitter. The fork's committed JSONs are not touched.
- For ours (outside this repo), the one-token change is `ubr_poly - lg.ubr` to `ubr_poly + lg.ubr` (his B9) or `ubr_poly` (centred). It needs a
  `model/tests` case with concrete expected numbers.
- I did not write a gated SBA constant: the audit finds no benefit (4.3).

## 6. Verified by running, and not

Verified by running this session: all rates, bucket tables and league means in sections 3-4 (script output); my numpy replica of
his `sbat`, SB% and `ubr` reproduces `public/data/BLM/hitters.json` to a maximum absolute difference of 0.0 on SB%,
wSB vR and UBR vR over all 6545 rows; the pooled constants equal the workbook's `C39`, `C40`, `C41`, `H8`. The data
joins: BLM 2058 ratings matched 547 of 550 hitters; SSB 2043 matched 490 of 491; BLM 2057 and TGS 2044 matched on player id to
`ratings_history.db` pulls 4 and 29.

Inferred, not run: how the sheet's original `B19` was fitted (read from the formula and the B9 note, not re-fit); that
the original authors intended a centred UBR (the repo's own `UBRAA = UBR - rate x opportunities` in
`field_aggregator.py:112` points that way); that our production SSB build uses `lg.ubr` from 2043 alone (stated by the
27 engine boundary, not re-run). Not reproducible here: the clone-sim fits behind either side's curves.

Limits. One real season per row; bucket SEs of 0.0009 to 0.045 on attempts rate (largest in STE 75+, n = 23). The 2057 row uses
2058 constants, so it measures carry-over, not fit. His validators, the `ingest/ratings.py --selftest` and the tools tests were not run because no
engine or tool file changed.

## 7. Decisions for you

- **D1. UBR frame in the fork** (affects every hitter by the same amount).
  Options: (a) keep his `+C40` (league mean -0.37 versus real -0.28, error -0.09 runs/600 PA); (b) centred, apply the patch (mean -0.09, so
  within 0.1 of zero); (c) ours `-C40` (not offered; +0.5 over). Recommendation: (b), because wSB and BatR are already zero-centred, so BSR
  would then match the WAA definition. Effect is 0.03 wins per hitter; either choice is defensible and neither affects rankings among hitters.
- **D2. Ours.** If the dashboard pipeline stays live, flip `hitters.py:342`. If Phase 2 retires it, record this as one of the bugs adopting his engine removes
  (log it in `adopted.md` beside B5 and B8).
- **D3. SBA shape.** Neither curve fits the convex real shape (his floors at 0 below STE 45, ours is too flat). A shared fix belongs to row 5
  (the curve bake-off), not here.

Files: `docs/phase2/baserunning.md`, `docs/phase2/baserunning_audit.py`, `docs/phase2/baserunning_ubr_centered.patch`.
