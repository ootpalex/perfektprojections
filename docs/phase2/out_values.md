# Phase 2 row 2: fielding out values (audit, then results). GATED: nothing in the engine changed.

Branch `phase2/fielding`. Code: `tgs-viz/engine/out_values.py` (derivation, stdlib only), `tgs-viz/backtest/out_values_impact.py` (what it would change), `tgs-viz/engine/calib/BLM/out_values_candidate.json` (the candidate, read by nothing), `docs/phase2/out_values.patch` (the wiring, not applied). Tests: `tgs-viz/tools/tests/test_out_values.py`.
Companion: `docs/phase2/fielding_referee.md`.

## 1. What this means for you

On BLM's real 2058 data the infield out value comes out at 0.701 runs per play and the outfield at 0.834, against the 0.75 and 0.90 the engine uses. The derived values are 6.5% (infield) and 7.3% (outfield) below the shipped ones, so the shipped values are 6.9% and 7.9% above the league's own run values. Rankings barely depend on it (impact in section 6).

The "genuine conflict" in the plan is smaller than it looked. Three numbers were in play: the engine's hand-entered 0.75 / 0.90, our derivation (about 0.70 / 0.83), and an older ZR-based figure of about 0.50 / 0.66. The ZR figure is a different currency: OOTP's Zone Rating (ZR) credits about 0.43 to 0.62 runs per out in the infield on this data, 20% to 30% below the run value of the hit that out prevents, which matches his AUDIT.md §6 line that "zr under-credits ~25-35%". Both derivations agree that ZR is not the currency. Between his 0.75 / 0.90 and our 0.70 / 0.83 the gap is 6.5% to 7.3%.

The derived values reproduce on a second league: SSB 2043 gives 0.7015 / 0.8295 from its own data.

Impact if wired in on BLM (all 6545 priced hitters, 460 at MLB level): every infield `RunsP` shrinks by exactly 6.5% and every outfield `RunsP` range term by 7.3% (arm and catcher terms do not move). The MLB mean `Max WAA` changes by -0.034 WAA, the largest single move is -0.183 WAA (1.8 runs; an elite shortstop), 42 of 460 MLB hitters move more than 0.1 WAA, and 2 of 460 change their best position. The spread between the 90th and 10th percentile of `RunsP` among MLB shortstops falls from 37.2 to 34.8 runs and for center fielders from 38.0 to 35.3.

It is built gated: `out_values_candidate.json` plus an unapplied patch. Your decision, section 8.

## 2. Audit: every input traced

Tags: 🟢 computed from our real data, 🟡 borrowed constant, 🔵 deliberate assumption.

| Input | Source | Tag | Notes |
|---|---|---|---|
| league runs and outs | `Hitting_Data.csv` (BLM 2058): 20712 runs, 130771 outs, 0.1584 runs per out | 🟢 | outs = AB - hits + SF + SH + GIDP + CS, as `hitting_calc` |
| run values of BB, 1B, 2B, 3B, HR relative to the league | `metadata_calibrate.run_values`: BB = 0.14 + R/Out; 1B = BB + 0.155; 2B = 1B + 0.30; 3B = 2B + 0.27; HR = 1.4 | 🟡 | the four step constants are the sheet's linear weights, inherited from standard linear-weights tables. The engine's own wOBA weights, WAA and hitter ratings all use them, so using them here keeps hitters and fielders in one currency. |
| run value of an out: `runs_minus = total event runs / non-event plate appearances` = 0.2479 | `woba_engine` | 🟢 | self-calibrating to the league |
| 1B / 2B / 3B above an out: 0.7013 / 1.0013 / 1.2713 runs | `rv + runs_minus` | 🟢 given the 🟡 above | reproduced by hand in the test |
| chances (Plays A), made (Plays M), errors per position | `Fielding_Data.csv` BIZ-R/L/E/U/Z/I, BIZ-Rm..Zm, E | 🟢 | impossible bucket (BIZ-I) counts as a chance, is never made |
| hits in a zone = Plays A - Plays M - E | accounting identity | 🟢 | closes to 97.1% of league singles (check 2) |
| "every 2B and 3B is an outfield event" | assumed | 🔵 | cannot be tested on this data; sensitivity in check 4 |
| infielders prevent only singles | assumed | 🔵 | follows from the same assumption |
| pitcher and catcher zones not in the out value | `Fielding_Data` has no pitcher table | 🔵 | SSB's pitcher table shows 327 hits against 25194 league singles |
| the engine's 0.75 / 0.90 | `metadata_calibrate.STATICS` F38 / F39, workbook H38 / H39 | 🟡 | hand-entered; no derivation in the repo |
| "zone identity proves 0.75 / 0.9" | AUDIT.md §6, one line | 🟡 | no script or derivation in the repo. I reconstructed it from the dashboard's `OUT_VALUE_V2_FINDINGS.md` (the Plays A - Plays M - E = hits accounting); if he means something else, that sentence is unverified. |
| OOTP's ZR | `Fielding_Data` ZR column | 🟢 as data; its run scale is OOTP's own | |

## 3. The two derivations

Derivation A, linear weights plus the hit mix the outfield fails to convert (ours; reproduces the dashboard's `_derive_out_values` on this data to 1e-15):

```
inf_out = 1B above an out                                  = 0.7013
OF hits  = (chances - made - errors) summed over LF, CF, RF = 21,140
OF 1B    = OF hits - (league 2B + 3B)                       = 21,140 - 8,742 = 12,398
mix      = 1B 0.586 / 2B 0.381 / 3B 0.032
of_out   = 0.586 x 0.7013 + 0.381 x 1.0013 + 0.032 x 1.2713 = 0.8341
```

Derivation B, ZR scale: for each position regress OOTP's ZR on outs made above the position's league average (players with at least 20 chances). Outs have counting noise and ZR has its own, so the forward slope is biased low and the inverse of the reverse slope is biased high; the true slope lies between when both carry error. Runs per out, forward to reverse:

| pos | BLM 2058 | SSB 2043 |
|---|---|---|
| 1B | 0.297 to 0.496 (n 77, r 0.77) | 0.276 to 0.721 (n 74, r 0.62) |
| 2B | 0.434 to 0.562 (n 97, r 0.88) | 0.409 to 0.558 (n 90, r 0.86) |
| 3B | 0.490 to 0.587 (n 92, r 0.91) | 0.462 to 0.616 (n 89, r 0.87) |
| SS | 0.429 to 0.586 (n 93, r 0.86) | 0.437 to 0.548 (n 97, r 0.89) |
| LF | 0.250 to 1.103 (n 102, r 0.48) | 0.314 to 0.533 (n 94, r 0.77) |
| CF | 0.371 to 0.679 (n 83, r 0.74) | 0.522 to 0.741 (n 84, r 0.84) |
| RF | 0.264 to 0.694 (n 100, r 0.62) | 0.180 to 0.599 (n 104, r 0.55) |

The brackets for 2B, 3B and SS in both leagues (upper ends 0.55 to 0.62) lie below 0.70. The brackets for CF and RF lie below 0.83 in both leagues. Corner-outfield and first-base brackets are wide because r is 0.5 to 0.8.

## 4. Verification (run this session)

1. Tool output equals the dashboard code: `out_values.derive_out_values` and the dashboard's `_derive_out_values` give (0.7013002396748097, 0.834120485653996) on BLM 2058.
2. Accounting closes. Seven-position balls in zone (Plays A) = 114,366 against 120,523 approximate balls in play (0.949; pitcher and catcher zones are the rest). Infield hits 13,037 + outfield singles 12,398 = 25,435 of 26,202 league singles (0.971). In SSB 2043, whose file has a pitcher table, the pitcher zone adds 327 hits and closes 44% of the 743-single shortfall. Same ratio for BLM 2057: 0.971.
3. Zone identity as a level check. Runs implied by the league's unconverted chances at a candidate out value, divided by the run value above an out of every non-HR hit the league actually hit:

| candidate | BLM 2058 | BLM 2057 | SSB 2043 |
|---|---|---|---|
| frozen 0.75 / 0.90 | 1.055 | 1.043 | 1.058 |
| derived | 0.980 | 0.981 | 0.980 |
| ZR-implied 0.50 / 0.66 | 0.749 | 0.735 | 0.751 |

   The derived values read 0.98 because the field positions cover 97.1% of singles; that is an arithmetic property of the derivation, not an independent confirmation. What the test does show: 0.75 / 0.90 price the failed plays 4% to 6% above what the hits cost (up to 9% if the 3% of singles outside the field positions are pitcher-zone hits, which would put the exact answer near 0.97), and 0.50 / 0.66 price them 25% below. The accounting uncertainty (about 3%) cannot explain a 25% gap.
4. Sensitivity of `of_out` to the 🔵 "every 2B and 3B is an outfield event": 100% in the outfield 0.8341; 95% 0.8275; 90% 0.8208; 80% 0.8076. `inf_out` does not depend on it.
5. Second leagues: BLM 2057 (OOTP actuals, `opps_0..5`): 0.6999 / 0.8510 (mix 0.531 / 0.430 / 0.039). SSB 2043: 0.7015 / 0.8295. BLM 2057's outfield value is 2% above 2058's; its infield and outfield hit counts differ from 2058 because its chance flow differs (fielding_referee.md section 5).
6. The run-value steps against the sim: `calib/BLM/currency.json` holds a team-clone-year regression (n = 352) of runs on event counts. Its event-to-event differences are within 1.2 standard errors of the sheet's steps: 1B - BB 0.139 vs 0.155, 2B - 1B 0.282 vs 0.30, 3B - 2B 0.101 (SE 0.142) vs 0.27 (z -1.1, -0.7, -1.2, computed from the reported SEs ignoring covariances). Its "out" coefficient (-0.095) is not usable: team outs are nearly constant across team-seasons (27 per game), so that coefficient acts as an intercept and cannot fix the level of a single above an out. Taken at face value it would give 1B above out of 0.58 and a 0.58 / 0.70 pair; I treat that as unidentified, not as evidence. Sim data to replicate it is not on this machine.
7. Candidate wiring runs: `python tgs-viz/engine/metadata_calibrate.py --inputs-dir calib/BLM/metadata_inputs --derived-out-values --json x.json` gives F38 = 0.7013002396748097, F39 = 0.834120485653996 (patch applied then reverted); `git apply --check` of `out_values.patch` passes on the committed file.
8. The impact harness reproduces production: re-pricing BLM's 6545 records with the production path and the unchanged workbook values gives max difference 0.0 against `public/data/BLM/hitters.json` in `Max WAA wtd`, `SS RunsP`, `CF RunsP`, `1B WAA wtd`.

Not verified: that the sim's actual run scoring prices a converted play at 0.70 / 0.83. That needs the clone archives (team runs allowed against team unconverted chances) or a swapped-fielder A/B sim; neither is on this machine.

## 5. Verdict on the conflict

- Holds: derivation A, 0.701 / 0.834, with the accounting uncertainty (about 3%) and the 🔵 outfield assumption (down to 0.808 if a fifth of extra-base hits were infield events).
- Does not hold as a run value: the ZR scale, 0.43 to 0.62 in the infield. It is a statement about OOTP's ZR, and the engine's hitters are priced in linear-weights runs: a single costs a hitter's team 0.70 runs above an out in the engine's own wOBA weights. A fielding value of 0.50 would price the same single at 0.50 when a fielder prevents it. (Reasoning, not a measurement.)
- Close but 6.9% (infield) and 7.9% (outfield) above the derived value: the engine's hand-entered 0.75 / 0.90. Hand-entered also means a league with a different run environment (TGS, a different R per out) keeps the same numbers.
- Note for the dashboard's CLAUDE.md: its example "the real Zone-Rating data implies ~0.50/0.66" is the figure the dashboard's own `OAA_PIPELINE_AUDIT.md` red flag 1 later marked RESOLVED ("it's ~right"; the ZR figure folds in the 6-bucket over-spread). The CLAUDE.md text is out of date.

## 6. Candidate and its impact on BLM (computed)

Candidate: `H38 = 0.7013` (infield, x0.9351 of shipped), `H39 = 0.8341` (outfield, x0.9268). Source: BLM 2058 `metadata_inputs`.

`RunsP` among MLB hitters listed at the position (runs per 1200-inning slot; the arm term does not move in the outfield):

| pos | n | sd shipped | sd candidate | mean abs change | max abs change | p90 - p10 shipped | p90 - p10 candidate |
|---|---|---|---|---|---|---|---|
| 1B | 57 | 3.11 | 2.91 | 0.16 | 0.48 | 8.4 | 7.8 |
| 2B | 71 | 12.23 | 11.44 | 0.72 | 1.36 | 28.5 | 26.6 |
| 3B | 45 | 11.42 | 10.67 | 0.59 | 2.21 | 28.6 | 26.7 |
| SS | 52 | 15.08 | 14.10 | 0.84 | 2.09 | 37.2 | 34.8 |
| LF | 59 | 10.81 | 10.03 | 0.71 | 1.40 | 26.7 | 24.8 |
| CF | 59 | 13.74 | 12.75 | 0.90 | 1.80 | 38.0 | 35.3 |
| RF | 49 | 10.27 | 9.53 | 0.55 | 1.72 | 27.9 | 25.8 |

`Max WAA wtd` (wins above average, 1 WAA = 10.036 runs for BLM), named players:

| player | listed | best pos | shipped | candidate | change | best-pos RunsP shipped -> candidate |
|---|---|---|---|---|---|---|
| Jeff Redpath | SS | SS | 2.16 | 1.98 | -0.183 | 28.2 -> 26.4 |
| Gary Gentile | SS | SS | 0.40 | 0.22 | -0.183 | 28.2 -> 26.4 |
| Nick Bergstrom | CF | CF | 0.40 | 0.22 | -0.180 | 24.7 -> 22.9 |
| Alex Lujan | CF | CF | 2.08 | 1.90 | -0.175 | 24.6 -> 22.8 |
| Sérgio Simard (top of the MLB board) | 1B | 1B | 6.29 | 6.27 | -0.020 | 3.1 -> 2.9 |
| Teruyuki Yoshimoto | SS | SS | 5.28 | 5.16 | -0.111 | 17.2 -> 16.1 |
| Jonathan Skinner | SS | SS | 5.15 | 5.00 | -0.154 | 23.8 -> 22.2 |
| Ewan Titterington | SS | 2B | 4.88 | 4.72 | -0.156 | 24.1 -> 22.5 |
| Marco Castello | 2B | 2B | 3.93 | 3.80 | -0.134 | 20.7 -> 19.3 |
| Ryan Adcock (largest rise) | 1B | 1B | 1.63 | 1.65 | +0.016 | -2.4 -> -2.3 |

Aggregate: MLB `Max WAA wtd` mean change -0.034 (mean absolute 0.035), max absolute 0.183, 42 of 460 move more than 0.1. Best-position label changes: Chris Caldas (2B to SS, WAA -0.127 to -0.236) and Bobby Mendez (RF to 3B, -9.060 to -9.056), both marginal. In the top six of the MLB board one pair swaps: Titterington (4.88 to 4.72) falls below Ballard (4.84 to 4.77).

Side effect to know: `fielding_curves_fit.py`'s ±3-run gate multiplies by `H38` / `H39` read from `extracted/<LG>_hitters_datapoints.json`; after a wiring the gate would be 6.5% / 7.3% tighter in runs. The curves themselves (rates per chance) do not depend on the out value. The referee slope does not either.

## 7. Flags and how each is resolved

1. The step constants (0.14, 0.155, 0.30, 0.27) are borrowed. Resolved to the extent that matters: the sim's own event-to-event differences are within 1.2 SEs (check 6). Not resolved: the level of a single above an out, which the sim regression cannot identify.
2. "All extra-base hits are outfield events" is assumed. Bounded: of_out between 0.808 and 0.834 for 80% to 100%.
3. The accounting covers 97.1% of singles. The pitcher zone explains 44% of the miss in SSB; the rest is not located.
4. BLM 2057 and 2058 split hits between infield and outfield differently (infield 15,751 vs 13,037; outfield 18,034 vs 21,140) for the same league-wide total. Cause not determined; the derived outfield value differs by 2%.
5. The AUDIT.md "zone identity" has no written derivation. Reconstructed (section 2); unverified as his meaning.
6. TGS cannot be run: it has no `metadata_inputs` CSVs on disk (it reads the 25 Metadata.xlsx tabs). The tool exits with a message. TGS would also get its own result because its run environment differs.
7. SSB is priced with BLM's `H38` / `H39` in the fork (verified in fielding_referee.md). SSB's own derived values (0.7015 / 0.8295) are within 0.6% of BLM's, so one candidate fits both.

## 8. Decisions for you

1. Wire the derived out values or keep 0.75 / 0.90. Options: (a) keep as is; (b) apply `out_values.patch` and run the Recalibrate step with `--derived-out-values`, so each league self-derives; (c) apply only to BLM and SSB by hand-entering 0.70 / 0.83. Evidence: the derived values are 6.5% and 7.3% below his, replicate on a second league, and the effect is at most 0.18 WAA per player with 2 of 460 best-position changes. I recommend (b) at the next Recalibrate, because it makes the number follow each league's run environment and costs nothing else. If you prefer not to touch money numbers for a 7% change, (a) is defensible; the cost is that the number stays hand-entered.
2. If (b): `Recalibrate BLM` (`tools/tasks.py:1537`, step `metadata_calibrate`) calls `metadata_calibrate.py`; adding `--derived-out-values` to that step is a one-line change I did not make.
3. Settle the currency with the sims, when the clone archives are available: regress team runs allowed on team unconverted chances, or run a swapped-fielder A/B. That is the only test of whether the sim prices a converted play at 0.70 / 0.83.

## 9. Reproduce

```
python tgs-viz/engine/out_values.py --league BLM              # derivation + identity + ZR bracket + sensitivity
python tgs-viz/engine/out_values.py --league BLM --write      # candidate file
$PY tgs-viz/backtest/out_values_impact.py --league BLM --top 6
python -m pytest tgs-viz/tools/tests/test_out_values.py -q
git apply --check docs/phase2/out_values.patch                # the unapplied wiring
```
