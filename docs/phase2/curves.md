# Phase 2 row 5: rating-to-rate curves, three-way bake-off

*2026-10-03, branch `phase2/curves` off `phase2-model` (his `9dadf36` + Phase 0/1 commits). Audit
first, code second, results last. Tags: 🟢 computed from real data · 🟡 borrowed constant ·
🔵 deliberate assumption. Each claim is marked **verified** (read or run this session) or
**inferred**.*

## Bottom line

The piecewise family, as wired in our pipeline, does not beat his curves on the two real OOTP-27 seasons on disk, so nothing in his engine should change on this evidence. It wins no pitching block on either season by the 5% margin and no hitting block on both seasons. The cause is the sim substrate and the way its knots slide with the league average, not the family: our family with its slopes refit on his archive bucket means scores 0.428 percentage points of RMSE (geometric mean over 8 pitching blocks, BLM 2058) against 0.420 for his S-curve and 0.464 for his two-line. The three-way machinery is built, off by default, and reproduces every committed choice and output; it picks the committed curve in all 8 BLM pitching blocks.

Terms used below. Block = one rating-to-rate relationship. SO = strikeout rate, uBB = unintentional-walk rate, HR = home-run rate, HHR = rate of non-home-run hits per ball put in play (the BABIP-like block), XBH = extra-base share of non-home-run hits, T3B = triple share of extra-base hits. SP / RP = starter / reliever tab. BF = batters faced, PA = plate appearances. RMSE = root-mean-square error. "Wired" = the knots and slopes committed in our `data_points.py`. "Gate" = `scurve_fit.live_gate`, defined in section 1.4.

## 0. What this item is, and the constraint

Three families map a displayed rating to an event rate:

| Family | Whose | Shape | Where it lives |
|---|---|---|---|
| two-line | his | two straight lines meeting at rating 50, level-shifted to the live league | `pitchers.py:243 twoline_rate`, `hitters.py piece()`; constants from `The Sheets <LG>/The Sheet *.xlsx` |
| S-curve | his | `A + B/(1+e^(-k(r-m)))`, plus an elite-K hinge on SO | `scurve_fit.py`, chosen per block by `promote_scurves.py choose()`, stored in `calib/<LG>/scurves.json` |
| piecewise | ours | continuous multi-knot line, slopes per rating point, anchored at the league average rating | `ootp-dashboard model/src/data_points.py:98-130, 485-790`, evaluator `model/src/utils.py piecewise_delta` |

His clone-sim archives are not on this machine. Nothing is refit here. Every curve below is a
fitted curve read from disk and compared on a real season.

## 1. Input trace (written before any code)

### 1.1 His S-curve and two-line (pitching)

| Input | Tag | Provenance (verified by reading) |
|---|---|---|
| Archive pools `calib/BLM/{Batting,Pitching,Pitchers}.csv` | 🟢 | 7 pooled BLM clone sims (`ootp/README.md`: "BLM pools 7 such runs"); the files themselves are **not on disk**. Pool sizes are recorded in the preview: SP n = 160, RP n = 224 players. |
| Engine version of those clones | 🟢 (inferred from config) | `ootp/leagues.json` has BLM `"game": "27"`; `hitters.py` comment says "BLM/OOTP27" for the SB% plateau. TGS is `"game": "26"`. The date the BLM clones were simmed relative to BLM's move to 27 is not on disk. |
| Logistic (A, B, k, m) | 🟢 | BF-weighted least squares on career rates by rating (`scurve_fit.py fit_logistic`), asymptote bounds from observed bucket range, sign enforced per block. |
| Live-scale drift (a, c) | 🟢 fitted on the live season | `calibrate_scale`: affine map of the live rating onto the clone rating, fitted on the live per-player points. SP SO has a = 1.265, c = +8.25; every other block fell back to the identity (1, 0). **This uses the same season the gate then scores.** |
| Elite-K hinge (SO) | 🟢 fitted on the live season | slope `s` is a BF-weighted WLS on the live tail (`fit: "live"`, n = 22 SP tail pitchers). Same season as the gate. |
| Two-line slopes and intercepts | 🟢 | WLS on the same archive pools, split at 50, centred on the sheet's metadata anchor (`constants-latest.json`; reproduced by `scurve_fit.py` "pool fidelity"). Read at run time from `The Sheet Pitchers.xlsx`. |
| Level offset (S-curve and two-line) | 🟢 | one number per block: league actual rate minus the curve's BF-weighted mean over the live population. |
| 5% margin, "monotone" test | 🔵 | `promote_scurves.py MARGIN = 0.05`; chosen by the user for BLM on 2026-10-01. |
| Gate data | 🟢 | `calib/BLM/metadata_inputs/{SP,RP}_{Data,Ratings}.csv`, season 2058, in-game date 2058-12-30, ratings pull 2026-09-13 (`manifest.json`). 2058 is BLM's first OOTP-27 season (`BLM-ATL/league.json engineFirstSeason {27: 2058}`). |

### 1.2 His hitting curves

Two-line per block with a seam at 50 (`hitters.py piece()`), plus the archive-measured tail
corrections `hitter_tails.json` (`tadj`, zero outside five audited tail regions) that the live
pipeline applies for both leagues (`ratings.py live_hitter_tails`). There is no S-curve path for
hitters. 🟢 constants from the BLM archive; 🔵 seam at 50.

### 1.3 Our piecewise family

| Input | Tag | Provenance |
|---|---|---|
| Knots and slopes (13 pitching + 6 hitting rate blocks) | 🟢 for the shape, from designed test-league sims (the "H-pool", 60 jobs, about 500 seasons, 100% right-handed, neutral GB tendency, neutral parks); 🟡 as an engine-27 transfer | `KNOT_DECISIONS_27.md` via `data_points.py` Section 1b. Fits have R² 0.997-0.9998 against the H-pool bins, not against any real league. |
| `sp_hrr` / `rp_hrr` | 🟡 | Kept at the older "C-pool" lock because the real-SSB referee rejected the H-pool candidate (1.72x and 1.46x real). |
| Calibration average (`_CALIB_AVG_27`) | 🟢 | Pool averages; used only to turn absolute knots into offsets from the league average. |
| Relative-knot placement | 🔵 | Knots slide with each league's average rating (`lg.avg_*`, BF- or PA-weighted, vR/vL blended by the matchup share). |
| Stuff cap at 88 | 🔵 | Decision D24. |
| SP-section -5 / RP-section +5 on STU by listed position | 🔵 | Same convention his engine applies as a flat +/-5 (`pitchers.py statline`). The gate scores raw displayed ratings for every family, so it never applies this shift to any curve. |
| Real-league referee | 🟢 | SSB 2043 (OOTP 27). The knot locks for `sp_hrr`/`rp_hrr` were decided on that season. So SSB 2043 is **not out-of-sample for our family**. |

### 1.4 The gate (what the metric needs)

`scurve_fit.py live_gate`, read in full. For one role and block it takes:

1. one row per pitcher in the role's Data tab: season rate, weight = the rate's denominator;
2. that pitcher's raw vR and vL rating, blended by the role's vR share of BF;
3. each curve evaluated at both ratings and share-blended, then level-matched (its own
   weighted mean miss is removed);
4. 5-point buckets of the vR rating inside [20, 80]; metric = denominator-weighted RMS over
   buckets of (bucket mean actual minus bucket mean predicted).

Everything on that list is on disk for BLM 2058. It does **not** need the clone archives. The
archives are needed only to fit a curve, not to score one.

## 2. What is on disk, and what is not

| Need | On disk? | Where |
|---|---|---|
| His fitted S-curve parameters, all 8 pitching blocks (chosen or not) | yes | `calib/BLM/scurves-preview.json` (`scurves.json` holds only the 5 chosen) |
| His two-line constants | yes | `The Sheets BLM/The Sheet {Pitchers,Hitters}.xlsx`; equal to `constants-latest.json` (checked: hEYE, lEye, hPOW, hK's, hBABIP, hGAP, lSPE, hSTU all equal to the last digit) |
| His hitter tail corrections | yes | `calib/BLM/hitter_tails.json` |
| Our piecewise knots and slopes | yes | `ootp-dashboard model/src/data_points.py` @ 8c6337a (transcribed; parity run in section 3) |
| Real season, OOTP 27, BLM | yes | `calib/BLM/metadata_inputs` = season 2058 (SP 267, RP 391 pitchers; 547 hitters) |
| Real season, OOTP 27, SSB | yes | `ootp-dashboard leagues/SSB/metadata/2043` (SP 238, RP 243 pitchers; 490 hitters) |
| Real season, OOTP 26 | yes, unusable here | BLM 2057 actuals and SSB 2041/2042 are the 26 engine; the piecewise family is a 27 calibration |
| His clone-sim pools (`calib/BLM/{Batting,Pitching,Pitchers,Hitters}.csv`) | **no** | needed only to FIT a curve on his substrate |
| His archive bucket means | partly | `scurves-preview.json` `blocks.*.buckets` (13 five-point rungs per pitching block); `hitter_tails.json` `report` (tail regions only) |
| Our designed-sim bins | yes, outside the repo | `ootp27-conversion/test-league-design/outputs/viz/hpool_hitpit_bins.json` |

The gate (section 1.4) scores a curve; it does not fit one. So all three families can be scored on both real seasons with the fixed curves on disk. What cannot be done is fitting our family to his substrate, which is the comparison that separates the family from the substrate (section 7).

## 3. Verification runs (all executed this session)

1. **The N-curve gate reproduces his committed gate.** `pw_curves.live_gate_n` with his S-curve (rebuilt from `scurves-preview.json`) and his two-line (from the sheet) reproduces `live_gate` of all 8 pitching blocks: worst absolute difference in RMSE 2.6e-18 (rate units), same n and weights, bucket means equal to 1e-10. Test: `GateReproductionTest`.
2. **Transcription parity with our evaluator.** All 18 pitching and hitting specs (knots, slopes, `relative`, clamp flags) were compared with `DEFAULT_{PITCHING,HITTING}_REG_COEFFS_27` objects in the ootp-dashboard checkout, and our `piecewise_delta` against `pw_curves` at every 0.5 rating point from 15 to 95 with a random anchor: worst absolute difference 0.0. Frozen values at anchor 50 are pinned in `TranscriptionTest`.
3. **Live anchors equal the sheet's anchors.** The BLM SP Stuff anchor computed from the ratings CSV is 47.415, equal to `metadata-latest.json` (47.415008918583915).
4. **Hand re-derivation of one curve value.** BLM SP Stuff: anchor 47.415; wired knots 32/42/78 minus the calibration average 56.605 plus the anchor give 22.81 / 32.81 / 68.81. delta(70) = 0.00339 x (68.81 - 47.415) + 0.01078 x (70 - 68.81) = 0.08536; the evaluator gives 0.08536.
5. **Gating proof.**
   * `hitters.py` and `pitchers.py` main() for TGS and BLM, `build_json.py` for TGS and BLM, `ingest/ratings.py --selftest`: output byte-identical to the output at the base commit (compared with `cmp`). These validators already report FAIL / MISMATCH / CHECK at the base commit (pitchers: worst abs diff 35.9 TGS, 16.9 BLM); this change moves nothing.
   * `pitchers.compute` before and after the `piecewise` branch: 12,330 computes (every eligible BLM sheet pitcher, with and without the committed `scurves.json`) are exactly equal as dicts.
   * `promote_scurves.py` on a copy of `calib/BLM`: default and `--three-way` rebuild the committed `scurves.json` (all keys except `promoted_at`, and `gate` text under the flag). `choose3` equals `choose` for all 8 committed preview blocks.
   * `tools/tests` loop: see section 11.

## 4. Results on the real seasons

The metric is the gate's: level-matched, denominator-weighted bucket RMSE, in percentage points of the block rate (for example, SP Stuff is K / (BF - HBP - BB), so 0.60 means a 0.60-point miss in K%). `n` is players scored, `W` is the summed denominator. "Noise floor" is the binomial sampling noise of the bucket means, sqrt(sum_b p_b (1 - p_b) / W); it is approximate because the gate's level-matching removes one degree of freedom and because true talent beyond ratings adds noise. Intervals are percentile intervals from 2,000 player-resamples. The metric contains sampling noise, so a resample inflates it and the point estimate can sit at the edge of the interval; read the interval for sign and size, not as a symmetric error bar.

Rule applied: the two-line is the incumbent. The S-curve replaces it only if more than 5% better (the committed rule). The piecewise then replaces the current pick only if more than 5% better than it (`choose3`). Hitting has no S-curve; the incumbent is the two-line plus tails, which is how the live pipeline runs BLM.


#### BLM-2058 pitching (RMSE in percentage points of the block rate; gain = 1 - RMSE_A / RMSE_B, positive = A better)

| role | block | n | W (BF) | noise floor | two-line | S-curve | piecewise | S vs two [95% CI] | piecewise vs two [95% CI] | piecewise vs S | 3-way pick |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SP | SO | 267 | 100,296 | 0.45 | 0.81 | 0.60 | 1.55 | +26.4% [-15.0%, +37.7%] | -90.8% [-117.4%, -46.9%] | -159.3% | S-curve |
| SP | uBB | 267 | 108,637 | 0.28 | 0.39 | 0.43 | 0.56 | -10.4% [-34.3%, +14.6%] | -42.8% [-100.4%, +19.9%] | -29.3% | two-line |
| SP | HR | 267 | 100,296 | 0.20 | 0.23 | 0.19 | 0.28 | +17.0% [-4.7%, +25.5%] | -23.0% [-53.2%, +8.7%] | -48.2% | S-curve |
| SP | HHR | 267 | 72,532 | 0.44 | 0.35 | 0.35 | 0.36 | +0.4% [-8.6%, +8.6%] | -3.8% [-9.0%, +5.8%] | -4.2% | two-line |
| RP | SO | 391 | 66,463 | 0.58 | 0.71 | 0.80 | 1.11 | -12.7% [-55.2%, +23.4%] | -56.0% [-104.5%, +13.7%] | -38.4% | two-line |
| RP | uBB | 391 | 72,185 | 0.34 | 0.72 | 0.53 | 0.65 | +26.7% [+10.6%, +33.7%] | +9.8% [-30.4%, +36.6%] | -23.0% | S-curve |
| RP | HR | 391 | 66,463 | 0.29 | 0.28 | 0.25 | 0.26 | +11.0% [-14.6%, +23.1%] | +4.7% [-20.6%, +18.5%] | -7.2% | S-curve |
| RP | HHR | 391 | 47,406 | 0.62 | 0.59 | 0.55 | 0.55 | +7.8% [-2.2%, +11.5%] | +8.1% [-0.3%, +11.2%] | +0.3% | S-curve |

#### BLM-2058 hitting (incumbent = two-line + tails)

| block | n | W (PA or chain denominator) | noise floor | two-line | two-line + tails | piecewise | piecewise vs two+tails [95% CI] | pw + live drift (diagnostic) | pw, knots at calibration positions (diagnostic) | pick |
|---|---|---|---|---|---|---|---|---|---|---|
| uBB | 547 | 181,250 | 0.22 | 0.29 | 0.29 | 0.33 | -12.9% [-67.2%, +26.6%] | 0.20 (+31.6%) | 0.26 (+10.4%) | two-line + tails |
| HR | 547 | 167,195 | 0.17 | 0.28 | 0.28 | 0.17 | +37.6% [-5.4%, +44.9%] | 0.18 (+34.9%) | 0.34 (-21.6%) | piecewise |
| SO | 547 | 167,195 | 0.36 | 0.45 | 0.48 | 0.32 | +34.4% [-10.0%, +46.2%] | 0.31 (+35.2%) | 0.44 (+9.8%) | piecewise |
| HHR | 546 | 121,017 | 0.45 | 0.35 | 0.36 | 0.40 | -11.7% [-26.1%, +15.6%] | 0.40 (-11.7%) | 0.35 (+1.8%) | two-line + tails |
| XBH | 535 | 34,935 | 0.75 | 0.45 | 0.46 | 0.85 | -86.4% [-73.0%, -4.4%] | 0.51 (-10.8%) | 0.53 (-14.9%) | two-line + tails |
| T3B | 500 | 8,740 | 1.01 | 1.03 | 1.01 | 1.10 | -8.4% [-14.1%, +2.5%] | 1.10 (-8.4%) | 1.10 (-8.4%) | two-line + tails |

#### SSB-2043 pitching (RMSE in percentage points of the block rate; gain = 1 - RMSE_A / RMSE_B, positive = A better)

| role | block | n | W (BF) | noise floor | two-line | S-curve | piecewise | S vs two [95% CI] | piecewise vs two [95% CI] | piecewise vs S | 3-way pick |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SP | SO | 238 | 113,668 | 0.41 | 0.77 | 0.88 | 1.01 | -14.8% [-47.8%, +9.8%] | -30.9% [-64.3%, -3.7%] | -14.0% | two-line |
| SP | uBB | 238 | 123,203 | 0.29 | 0.42 | 0.42 | 0.41 | -1.6% [-22.8%, +15.6%] | +1.8% [-43.0%, +32.7%] | +3.3% | two-line |
| SP | HR | 238 | 113,668 | 0.19 | 0.14 | 0.10 | 0.21 | +30.3% [-13.0%, +35.1%] | -56.7% [-102.6%, +16.7%] | -124.7% | S-curve |
| SP | HHR | 238 | 82,173 | 0.42 | 0.61 | 0.63 | 0.60 | -4.2% [-7.5%, +1.2%] | +0.3% [-3.8%, +4.7%] | +4.3% | two-line |
| RP | SO | 243 | 43,734 | 0.70 | 0.56 | 0.79 | 0.81 | -40.9% [-78.2%, +19.2%] | -46.0% [-77.9%, +18.8%] | -3.7% | two-line |
| RP | uBB | 243 | 47,567 | 0.46 | 0.34 | 0.48 | 1.00 | -41.3% [-67.9%, +10.3%] | -197.5% [-255.7%, -53.2%] | -110.5% | two-line |
| RP | HR | 243 | 43,734 | 0.33 | 0.41 | 0.33 | 0.37 | +17.7% [+1.7%, +24.3%] | +8.0% [-10.6%, +15.9%] | -11.7% | S-curve |
| RP | HHR | 242 | 30,973 | 0.75 | 0.73 | 0.75 | 0.73 | -2.8% [-6.5%, +3.2%] | +0.3% [-4.6%, +5.7%] | +3.1% | two-line |

#### SSB-2043 hitting (incumbent = two-line + tails)

| block | n | W (PA or chain denominator) | noise floor | two-line | two-line + tails | piecewise | piecewise vs two+tails [95% CI] | pw + live drift (diagnostic) | pw, knots at calibration positions (diagnostic) | pick |
|---|---|---|---|---|---|---|---|---|---|---|
| uBB | 490 | 171,236 | 0.23 | 0.42 | 0.42 | 0.54 | -29.0% [-80.8%, +18.2%] | 0.28 (+33.4%) | 0.20 (+50.7%) | two-line + tails |
| HR | 490 | 157,869 | 0.17 | 0.18 | 0.17 | 0.16 | +3.9% [-24.8%, +23.5%] | 0.14 (+18.8%) | 0.24 (-43.3%) | two-line + tails |
| SO | 490 | 157,869 | 0.39 | 0.38 | 0.35 | 0.52 | -47.1% [-81.5%, +9.0%] | 0.36 (-3.3%) | 0.51 (-45.4%) | two-line + tails |
| HHR | 490 | 114,199 | 0.46 | 0.42 | 0.43 | 0.44 | -1.3% [-20.9%, +18.3%] | 0.44 (-1.3%) | 0.42 (+3.4%) | two-line + tails |
| XBH | 490 | 33,115 | 0.78 | 0.59 | 0.62 | 0.97 | -56.8% [-63.5%, -3.6%] | 0.49 (+21.7%) | 0.54 (+13.4%) | two-line + tails |
| T3B | 470 | 7,930 | 1.08 | 0.87 | 0.86 | 0.90 | -4.9% [-11.0%, +7.7%] | 0.90 (-4.9%) | 0.90 (-4.9%) | two-line + tails |


### 4.1 Reading the results

* **The piecewise family, as wired, does not win a single pitching block on either season.** Best case against the two-line: BLM RP uBB +9.8% and RP HHR +8.1%, SSB RP HR +8.0%; every one has a 95% interval that includes zero. Against the S-curve the piecewise's best gain is 4.3% (SSB SP HHR), under the 5% margin. The 3-way pick equals today's committed choice in all 8 BLM blocks (SP SO and HR, RP uBB, HR, HHR on the S-curve; the rest on the two-line). The three-way machinery therefore changes no BLM choice on the data on disk.
* **Largest miss: SP Stuff.** BLM RMSE 1.55 points against 0.81 (two-line) and 0.60 (S-curve); SSB 1.01 against 0.77 and 0.88. The bucket table shows the cause: the wired elite-Stuff knot (78 on the calibration frame) slides to 68.8 on BLM because the live SP Stuff average (47.42) sits 9.2 points below the calibration average (56.605). The curve then climbs 0.0108 per point from 68.8 and predicts 36.8% K at the Stuff-75 bucket against an actual 28.2% (3 pitchers, 917 batters faced; binomial sd 1.5 points, so the miss is about 6 sd).
* **That slide is the dominant assumption.** Every pitching and hitting anchor is 1 to 10 points below its calibration average (table in section 6). Placing the knots at their calibration positions instead (`pw_abs`, a diagnostic) helps SP Stuff (1.55 to 0.94 on BLM) and RP Stuff (1.11 to 0.71) and hurts Move/HR (0.28 to 0.42 SP). Neither placement is uniformly right. A live-fitted shift would pick a partial slide; the diagnostic `pw_drift` (two free parameters, the same freedom the S-curve gets) lands within 1% of the two-line or better in 12 of 16 pitching cells (10 of 16 against the better of his two curves).
* **Hitting: no stable winner.** Against two-line + tails the piecewise wins HR (+37.6%) and SO (+34.4%) on BLM 2058 by more than 5%, but on SSB 2043 it gains +3.9% on HR and loses 47.1% on SO. It loses XBH on both seasons (-86% BLM, -57% SSB) and uBB on both (-13%, -29%). No hitting block clears the margin on both seasons.
* **The 5% margin is not resolved by n.** The bootstrap probability that a gain exceeds 5% is at most 0.94 for any piecewise cell (BLM hitting HR) and 0.63 for any pitching cell; for his own S-curve choices it is 0.56 to 1.00 (SP SO 0.81, SP HR 0.83, RP uBB 1.00, RP HR 0.56, RP HHR 0.61). The committed choices are mostly inside the noise of one season. This is a property of the committed gate, not of the third family.
* **In-sample status.** BLM 2058 scores the S-curve with parameters fitted on that same season (SP Stuff drift a = 1.265, c = +8.25, and the live-fitted elite hinge, 22 tail pitchers). So BLM 2058 flatters the S-curve. SSB 2043 is out of league and out of sample for his curves, and in-sample for our family (its knot locks were decided on it). Each family has one favourable cell.

## 5. Where the piecewise is better, by region

If the premise "his curves where live players are dense, our knees in the tails" held, the piecewise would have lower squared error than the better of his curves in the low (rung < 40) and high (rung > 60) regions more often than in the middle. It does not. Count of cells in which the piecewise squared error (summed over the gate's buckets, weighted by denominator) is lower than the best of his curves, per region:

| Cells | Low (< 40) | Middle (40-60) | High (> 60) |
|---|---|---|---|
| Pitching, 16 (8 blocks x 2 seasons) vs the better of two-line and S-curve | 4 | 2 | 3 |
| Hitting, 12 (6 blocks x 2 seasons) vs two-line + tails | 6 | 6 | 3 |

Comparing with the better of two of his curves is a stricter test for pitching than for hitting (one comparator). The bucket tables behind this are in `docs/phase2/curves_bakeoff.json`. No hybrid is supported by the gate, so none is built.

## 6. Why the wired piecewise misses: anchor slide

Live average rating minus the calibration average (display points). Relative knots move by this amount; absolute knots (SPE) do not.

| Block | Calibration avg | BLM 2058 | SSB 2043 |
|---|---|---|---|
| SP Stuff | 56.605 | 47.42 (-9.2) | 47.32 (-9.3) |
| SP Control | 57.313 | 48.95 (-8.4) | 50.33 (-7.0) |
| SP Move | 54.157 | 50.66 (-3.5) | 51.81 (-2.3) |
| RP Stuff | 57.217 | 49.27 (-7.9) | 51.92 (-5.3) |
| RP Control | 56.308 | 47.36 (-9.0) | 46.67 (-9.6) |
| RP Move | 53.866 | 47.98 (-5.9) | 48.96 (-4.9) |
| Hitter Eye | 56.038 | 48.71 (-7.3) | 48.63 (-7.4) |
| Hitter Power | 57.686 | 47.70 (-10.0) | 49.04 (-8.6) |
| Hitter AvoidK | 56.316 | 52.93 (-3.4) | 52.85 (-3.5) |
| Hitter BABIP | 57.407 | 52.08 (-5.3) | 52.01 (-5.4) |
| Hitter Gap | 57.508 | 52.69 (-4.8) | 52.10 (-5.4) |

The calibration pool is 6 to 10 points better-rated on average than either real league in the Stuff, Control and Power families. The live-fitted drift `c` in the diagnostic `pw_drift` is negative (-3 to -12 display points) in 15 of 18 non-identity fits, which says the best shift is smaller than the full slide. This matches the project note that the "knee is absolute-anchored" for Move. 🔵 relative placement is a deliberate assumption of the wired family (classification by predictor, spec section 2) and is the single assumption that most changes the bake-off.

## 7. Family versus substrate (supplementary; `docs/phase2/curves_hpool_check.py`)

The bake-off compares curves fit on different sim substrates. Two further runs separate the two effects. The first fits his families to our designed-sim bins; the second fits our family (the wired knots, slopes refit by weighted least squares in the ReLU basis) to his 13-rung archive bucket means in `scurves-preview.json`. The second is an approximation of a fit on his archive: 13 points identify a 3-to-5-slope curve loosely, and a few refit tail slopes are not monotone (SP uBB first slope +0.0008 per point, RP uBB first slope -0.0145). No live parameter (drift, hinge) is fitted for any curve in this table; only the level offset.

Geometric mean over the 8 pitching blocks of the gate RMSE, percentage points (n = 267 SP / 391 RP on BLM; 238 / 243 on SSB):

| Curve | Substrate | BLM 2058 | SSB 2043 |
|---|---|---|---|
| His two-line (BLM fit) | his | 0.464 | 0.443 |
| His S-curve (BLM fit, with its live drift and hinge) | his | 0.420 | 0.463 |
| **Our piecewise, slopes refit on his bucket means** | his (approx.) | **0.428** | **0.460** |
| His two-line family fit on our bins | ours | 0.566 | 0.575 |
| His logistic family fit on our bins | ours | 0.608 | 0.584 |
| Our piecewise, knots at calibration positions | ours | 0.563 | 0.538 |
| Our piecewise, as wired (knots slide) | ours | 0.556 | 0.574 |

Consequences:

* **The family is not the problem.** On his substrate the piecewise scores 0.428 against 0.464 (two-line) and 0.420 (S-curve) on BLM, and 0.460 against 0.443 and 0.463 on SSB. It beats his two-line in 5 of 8 BLM blocks and 2 of 8 SSB blocks, and his S-curve in 5 of 8 and 6 of 8.
* **The substrate is.** Fitting his two families to our designed-sim bins makes them 22% (two-line) and 45% (logistic) worse on BLM, and 30% and 26% worse on SSB, than the same families fit to his clone sims. The spread between families within one substrate is up to 9% in the geometric mean.
* **Same pattern in the slopes.** On his bucket means the SP Stuff mid-band slopes are 0.0069 (32-42) and 0.0032 (42-78) per point (wired: 0.0060 and 0.0034). The two tail segments disagree: below 32 the wired slope is 0.0131 against 0.0066 refit (2.0x), above 78 it is 0.0108 against 0.0163 refit (0.66x).
* **Limits.** The BLM comparison is the cell where his curves are in-sample (section 4.1), so 0.420 is a floor for his S-curve, not a fair average. The piecewise-on-his-buckets figure uses slopes fitted to archive bucket means and no live information, so it is not flattered by the live season. Hitting is covered by the same device in the table below.

Hitting (his engine has no hitting S-curve, so the only comparator is his two-line + tails). `hitter_tails.json` `report` carries 13-rung PA-weighted bucket means for five of the six blocks (Eye has no entry). Gate RMSE in percentage points, n = 547 (BLM) / 490 (SSB) hitters:

| Block | BLM his 2-line + tails | BLM pw as wired | BLM pw on his buckets | SSB his 2-line + tails | SSB pw as wired | SSB pw on his buckets |
|---|---|---|---|---|---|---|
| K (SO) | 0.484 | 0.317 | 0.374 | 0.352 | 0.518 | 0.357 |
| Power (HR) | 0.279 | 0.174 | 0.313 | 0.168 | 0.162 | 0.214 |
| BA (HHR) | 0.359 | 0.400 | 0.356 | 0.435 | 0.440 | 0.410 |
| Gap (XBH) | 0.458 | 0.853 | 0.522 | 0.620 | 0.973 | 0.487 |
| Speed (T3B) | 1.014 | 1.098 | 1.026 | 0.859 | 0.901 | 0.889 |
| Geometric mean | 0.468 | 0.461 | 0.467 | 0.424 | 0.503 | 0.423 |

On his bucket means the family ties his two-line + tails on hitting (0.467 vs 0.468 on BLM, 0.423 vs 0.424 on SSB) and beats it in 2 of 5 blocks on each season. As wired it ties on BLM and is 19% worse on SSB. The same conclusion as pitching: the family is not the cause of the as-wired losses.

## 8. What cannot be done without his sim archives

1. **Fit the piecewise family to his archive properly.** Needs `calib/BLM/Batting.csv`, `Pitching.csv`, `Pitchers.csv` for the pitching pools (160 SP, 224 RP players) and `Batting.csv` + `Hitters.csv` for the hitting pools. Then a knot-and-slope fit by BF- or PA-weighted least squares (with a monotone constraint and a knot-count rule such as the BIC one our research used), transported identically, scored with `curve_bakeoff.py`. Section 7 is the approximate version.
2. **Run `scurve_fit.py --pw` end to end.** `main()` needs the same pools (`build_pools`). The hook is verified through `pw_curves.preview_block` against the committed S-curve and two-line (test above), and the preview it would write is rebuilt by `curve_bakeoff.py --write-preview`, but `main()` itself was not run.
3. **A hitter S-curve.** None exists in his engine and none can be fit without the pools; the hitting comparison is two-line + tails against the piecewise only. The Eye (uBB) hitting block has no archive bucket table on disk, so it has no section 7 row.
4. **TGS.** TGS is OOTP 26 (`ootp/leagues.json`); the wired family is a 27 calibration, so `--pw` refuses it (`LEAGUES_27`). Our 26 constants are the same family as his two-line.
5. **A truly out-of-sample BLM season.** Needs one more BLM season on the 27 engine (2059), i.e. a StatsPlus pull and `metadata_inputs.py` (network). The 2057 BLM actuals on disk are the 26 engine.
6. **Role shift.** The gate scores raw ratings; the engine applies a flat +/-5 (or the role-stuff gain) to Stuff before the curve. Both his S-curve and our knots were fit on a role-adjusted rating frame in some form, and the gate never applies it. Checking the shifted frame needs per-pitcher listed-role data on the gate rows, which the role Data tabs do not carry.

## 9. Flags and how each was resolved

| Flag | Resolution |
|---|---|
| Our knots are relative to a pool average 6 to 10 points above the real leagues | Reported (section 6). Not changed: placement is the wired family's assumption. Both placements scored (`pw_abs`). |
| `calibrate_scale` (a, c) and the hinge slope are fit on the season the gate scores | Reported (4.1). A second season is needed to remove it (section 8, item 5). |
| Gate scores raw ratings, not role-shifted | Same convention for all three families; not changed (it is his gate). |
| Stuff cap 88 | Applied in the piecewise SO block only (`cap`), as ours does; his curves clamp to [20, 80]. Few ratings exceed 80. |
| The sheet's two-line constants could have drifted from the committed preview | Checked: the gate reproduces to 2.6e-18, so the sheet and the preview agree. |
| `scurves.json` is in the calibration fingerprint (`agecurve_fit.py:150`) | Nothing writes it. Any later promotion with a piecewise block would invalidate `.waa_cache` and DEV price tags; flagged for the decision. |
| Hitting two-line scored without the sheet's league constants (C33-C38), park and handedness multipliers | Level-matching removes the constants; park and handedness are common to all families. |
| Ratings are 5-point quantized | Same for all families; buckets are the 5-point rungs. |
| Sp/RP roles for SSB come from `sp_data.csv` / `rp_data.csv` (SP file has G up to 102) | Same population for all curves; the SSB share and anchors are cut to each role's pitchers. |
| Bootstrap intervals skewed by sampling noise in the metric | Stated in section 4; decisions rest on point estimates and the probability of exceeding the margin. |

## 10. Decisions for the user

1. **Wire the piecewise as a third family on the BLM pitching or hitting blocks?** Evidence: as wired it wins no pitching block and no hitting block on both seasons (section 4). Recommendation: no. The three-way machinery is in and costs nothing while off.
2. **Fit the piecewise on his archive (needs his CSVs, section 8 item 1).** Evidence: on his bucket means the family ties his S-curve on pitching (0.428 vs 0.420 points, BLM) and his two-line + tails on hitting (0.467 vs 0.468), without a live fit. Recommendation: yes, if his pools can be copied; this is the only comparison that tests the family itself.
3. **Anchor placement for the family** (slide with the league average, or fixed at calibration positions, or a live-fitted shift). Evidence: neither placement is uniformly better (section 4.1); a fitted shift is the S-curve's freedom. Recommendation: decide after item 2; do not choose on the current data.
4. **Sequential versus min-of-three margin in `choose3`.** Built sequentially (the piecewise must beat the current pick by more than 5%), so ties never switch the curve. Alternative: lowest RMSE among those beating the two-line. They differ on RP HHR here (S-curve vs piecewise, 0.3% apart). Recommendation: sequential.
5. **Engine hitting path.** The harness covers hitting; the engine (`hitters.compute`) has no curve-type hook and none was added. Recommendation: wait for item 2.

## 11. What was built

Branch `phase2/curves` (new files first; edits to his files are additive and default off):

| File | Change |
|---|---|
| `tgs-viz/engine/pw_curves.py` | new: the family (18 specs), N-curve gate, hitting loaders, `preview_block` hook |
| `tgs-viz/engine/curve_bakeoff.py` | new: report with bootstrap, `--write-preview` |
| `tgs-viz/engine/pitchers.py` | `+24` lines: `_pw_rate` and a `"type": "piecewise"` branch in `sc_rate` |
| `tgs-viz/engine/scurve_fit.py` | `+18`: `--pw` flag (default off; refuses non-27 leagues) |
| `tgs-viz/engine/promote_scurves.py` | `+45/-3`: `choose3`, `--three-way` (default off) |
| `tgs-viz/ingest/ratings.py` | `+4/-1`: `scurve_summary` labels piecewise blocks |
| `tgs-viz/tools/tests/test_pw_curves.py` | new: 26 tests |
| `docs/phase2/curves.md`, `curves_bakeoff.json`, `curves_hpool_check.py`, `curves_hpool_check.json` | this audit and its data |

Commands (from the worktree root, repo Python):

```
python tgs-viz/engine/curve_bakeoff.py --league BLM --ssb-dir <ootp-dashboard>/leagues/SSB/metadata/2043 --boot 2000 --json docs/phase2/curves_bakeoff.json
python docs/phase2/curves_hpool_check.py --bins <ootp27-conversion>/test-league-design/outputs/viz/hpool_hitpit_bins.json --ssb-dir <...>/2043 --json docs/phase2/curves_hpool_check.json
python -m pytest tgs-viz/tools/tests/test_pw_curves.py -q
```

Tools test loop (all files except `test_bat_equivalence.py`): test_catalog 9, test_doctor 6, test_metadata_paste 9, test_new_league 17, test_pw_curves 26 (new), test_run_task 39, test_settings_defaults 29: all passed. The new tests run in 0.5 s.
