# Phase 2 row 1: positional adjustments (audit, gated build)

Branch `phase2/posadj`. Nothing here changes a number the engine writes. The candidate
values sit in files the engine does not read, and each decision below is the user's.

Terms used. **posAdj** = the positional adjustment: runs added to a hitter's value for the
position he plays (his cells `P2..P10` in `metadata-latest.json`, which feed `W2..W10` and the
WAA lines in `engine/hitters.py`). **WAA** = wins above average. **RPW** = runs per win, 10.036
for BLM (`calib/BLM/currency.json`, the divisor `H30`). **IP** = innings played. **ZR** = OOTP's
Zone Rating, a per-player runs figure for plays made versus expected. **RunsP** = the engine's
projected fielding runs for a hitter at a position. **SE** = standard error. **Switcher** =
the method that compares the same fielder's ZR at two positions in one season.

## 1. What this means for you

1. **The plan's headline gap is mostly a unit mismatch inside our own pipeline, not a method
   difference.** Our frozen values are runs per 162 games (1458 IP). Our RunsP is per 1200 IP
   (catcher 1000 IP) and the posAdj is added to it with no rescale (`model/src/hitters.py:838-872`,
   `HitterLeagueParams.ip = 1200`, `ip_c = 1000` at `data_points.py:904-905`). So the dashboard's spectrum is 21.5% wider than the fielding
   runs it is added to (45.8% at catcher). Restated on his basis, the plan's 6.45-run gap at C
   falls to 1.40 and the 8.23-run gap at 1B falls to 5.91 (section 3, BLM). This is verified by
   reading and arithmetic; it is a finding about the dashboard, to be fixed there separately.
2. **Taking ours into his engine as published would move every BLM hitter by up to 0.82 wins
   a season and flip Best Pos for 12.4% of BLM MLB hitters** (57 of 460). Restated onto his
   basis it is up to 0.59 wins and 10.2% (47 of 460). Both are in section 5.
3. **Our frozen values were fitted entirely on OOTP 26 seasons** (BLM through 2056, SSB
   through 2042). BLM moved to OOTP 27 in 2058 and SSB in 2043. The ZR switcher half
   moves across that boundary for SSB (chi-square 37.2 on 6 degrees of freedom, against 6.3 for
   a control that crosses no boundary), and points the same way for LF, SS and CF in BLM
   (chi-square 10.6, short of the 12.6 five-percent line). Section 4.
4. **SSB currently uses BLM's posAdj.** SSB is priced on BLM's calibration. SSB's own candidate
   differs from BLM's P by up to 0.55 wins (LF), so the SSB side of the engine carries a
   league-mismatch error that is separate from every decision below (section 5).
5. **The tool works and matches both reference implementations.** It reproduces his `P2..P10`
   to 4e-15 and the dashboard's defence half to 0.005 runs per 1458 IP on the dashboard's own
   career history. The decisions are in section 7; nothing is blocked for lack of data except
   what is listed in section 8.

## 2. Input trace

Tags: 🟢 computed from real league data · 🟡 borrowed constant (provenance given) · 🔵
deliberate assumption (a decision for you, section 7).

| Input | Tag | Provenance and check |
|---|---|---|
| Hitting_Data per player (PA, AB, 1B..HR, BB, HP, SB, CS, UBR, R) | 🟢 | MLB season export. BLM 2058: 183,422 PA. Verified loaded. |
| Run values (BB = 0.14 + R/out, 1B = BB + 0.155, 2B = 1B + 0.3, 3B = 2B + 0.27, HR 1.4, SB 0.2, CS = -(2R/out + 0.075)) | 🟡 | His workbook port (`metadata_calibrate.run_values`). The dashboard derives its own weights; the two give OFF within the differences in section 3. |
| OFF per player = wRAA + base-running runs | 🟢 | His `hitting_calc`; reused unchanged, so the offence half has his definition of OFF. |
| Innings per position per player | 🟢 | Fielding_Data. BLM 2058: 43,254 IP at every position (30 teams x ~1,442). |
| Innings per PA (m2 = total fielding IP / total PA) and DH innings = PA x m2 minus fielding IP | 🟢 / 🔵 | m2 = 1.8845 (BLM 2058), 1.853-1.879 (SSB). Treating PA beyond fielding innings as DH time is his assumption. |
| Standard season: 1200 IP, catcher 1000 IP | 🟡 | Workbook statics `F33`, `F34`. RunsP uses the same, so this is the consistent basis. |
| ZR per player per position | 🟢 | Fielding_Data `ZR`. OOTP's ZR is on a compressed scale relative to engine run values (Row 2 implies about 0.67-0.73 of the 0.75/0.90 out values). Sensitivity in section 6. |
| Switcher weights (harmonic mean of the two innings) and the +1/-1 pair design | 🟡 | Zimmerman 2014 (THT) via the dashboard's research code. |
| ARM excluded from the switcher | 🔵 | The dashboard found that feeding ARM craters RF by about 7 runs; kept. |
| Recency: H_def 5 / cut_def 20 seasons; H_off 2.5 / cut_off 8 | 🔵 | Chosen in the dashboard's `SAMPLE_SIZE_AUDIT.md` on 42 (BLM) and 22 (SSB) season histories. On disk the fork has 2 BLM and 3 SSB seasons, so the cuts never bind and only the half-lives act. |
| Half defence, half offence | 🔵 | Zimmerman's 50/50. |
| C and DH from offence only | 🔵 | Catchers do not switch; the dashboard shelved two catcher corrections. |
| DH = min of the nine positions | 🔵 | Dashboard rule (locked 2026-05-28). |
| Field-8 mean = 0 centring | 🔵 | FanGraphs / Zimmerman convention. |
| LF and RF kept apart vs pooled | 🔵 | His engine pools them; the dashboard keeps them apart. |
| RPW 10.036 | 🟢 | His fitted currency; used only to express runs as wins. |

## 3. Both sets, verified as they exist now

Runs per standardized season unless stated. "Engine basis" = 1200 IP, catcher 1000 IP.

| | C | 1B | 2B | 3B | SS | LF | CF | RF | DH |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ours BLM, as published (1458 IP) | 16.10 | -13.10 | -2.30 | -0.70 | 9.60 | -8.40 | 5.10 | -6.20 | -13.10 |
| ours BLM, restated to engine basis | 11.04 | -10.78 | -1.89 | -0.58 | 7.90 | -6.91 | 4.20 | -5.10 | -10.78 |
| his BLM (`metadata-latest.json`, 2058, offence only) | 9.65 | -4.87 | -2.14 | -0.20 | 6.93 | -3.77 | 2.15 | -3.77 | -6.80 |
| plan's gap (ours as published minus his) | 6.45 | -8.23 | -0.16 | -0.50 | 2.67 | -4.63 | 2.95 | -2.43 | -6.30 |
| gap after the unit restatement | 1.40 | -5.91 | 0.25 | -0.38 | 0.97 | -3.14 | 2.05 | -1.33 | -3.98 |
| ours SSB, as published | 21.00 | -12.40 | -0.30 | -1.00 | 10.40 | -12.00 | 2.30 | -8.10 | -13.00 |
| ours SSB, restated | 14.40 | -10.21 | -0.25 | -0.82 | 8.56 | -9.88 | 1.89 | -6.67 | -10.70 |

Verified by running (`docs/phase2/pos_adj_audit_output.txt` section 1-3, `pos_adj_ours_repro_output.txt`):

- **His set**: the plan's numbers are exact. My port reproduces them to 4e-15, and his own
  `compute_cells` over the on-disk `metadata_inputs` reproduces `metadata-latest.json` to 0.0.
  His field-8 mean (C..RF, equal weights) is 0.50 runs.
- **Our set**: re-derived from the dashboard's 41-season BLM and 22-season SSB histories by
  running its research code directly (`pos_adj_ours_repro.py`). BLM comes out C 16.06,
  1B -13.05, 2B -2.31, 3B -0.72, SS 9.56, LF -8.40, CF 5.11, RF -6.25, DH -13.05; every value
  rounds to the literal. SSB comes out C 21.05, 1B -12.38, 2B -0.26, 3B -0.98, SS 10.37, LF -12.03,
  CF 2.34, RF -8.11, DH -12.98; every value rounds to the literal.
- **Two small drifts in the dashboard's defence-only spectrum** (`constants.js`): BLM RF is
  -4.9 where the data gives -4.955, and SSB CF is 9.4 where the data gives 9.34. Both are
  within 0.06.
- **My tool against the same history** (section 7 of the output): the defence half matches the
  dashboard's recorded `H5_C20` values to 0.005 runs per 1458 IP in both leagues, with identical
  observation counts (BLM 18,442; SSB 20,990). The blended values differ from the literals by at
  most 0.18 runs per 1458 IP in BLM and 0.21 in SSB, except SSB DH at 0.56. That residual is the
  difference in OFF (his run values and no pitcher-season exclusion against the dashboard's).

**Staircase from his BLM 2058 numbers to the candidate** (engine basis, section 3 of the
output). Each row adds one piece.

| step | C | 1B | 2B | 3B | SS | LF | CF | RF | DH |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| a. his P | 9.65 | -4.87 | -2.14 | -0.20 | 6.93 | -3.77 | 2.15 | -3.77 | -6.80 |
| b. LF and RF kept apart | 9.65 | -4.87 | -2.14 | -0.20 | 6.93 | -2.20 | 2.15 | -5.35 | -6.80 |
| c. centred, DH rule | 9.03 | -5.61 | -2.88 | -0.93 | 6.20 | -2.94 | 1.41 | -6.09 | -7.54 |
| d. plus the switcher half, 2058 only | 9.03 | -7.32 | -5.19 | -2.75 | 5.07 | -1.87 | 5.15 | -3.93 | -7.54 |
| e. plus 2057 (H_def 5, H_off 2.5) | 8.72 | -8.46 | -3.98 | -2.06 | 5.05 | -2.97 | 5.35 | -3.39 | -8.46 |

Centring moves every position by -0.74 runs per 1200 IP (a level shift, no ranking change). The
switcher is the largest single mover (2B -2.31, CF +3.74, 1B -1.71 from step c to d). Step e
shows how much one extra season moves things.

**Single-season offence is noisy.** The standard deviation of the offence-only value across seasons is
0.2-3.0 runs by position (BLM 2057 vs 2058: 1B 2.98; SSB 2041-43: 3B 2.93, RF 2.18). His 2058 1B
(-4.87) sits against -9.08 in 2057 and about -10.7 over the dashboard's 41-season history. This is
the evidence for his own AUDIT Phase B request for multi-season smoothing; the data on disk
cannot say whether 2058 is a noise draw or a 27-engine shift.

## 4. What crossing the OOTP 26 / 27 boundary does to the blend

Only 2043 (SSB) and 2058 (BLM) are on OOTP 27. The switcher half was tested by comparing the
last OOTP 26 data with the first OOTP 27 season, bootstrap SEs from 500 resamples of the switch
observations (they ignore that one player appears in several pairs, so they are a floor).
Values are runs per 1200 IP.

| position | SSB 2041-42 (26) | SSB 2043 (27) | change | z |
|---|--:|--:|--:|--:|
| 1B | -4.58 ± 0.92 | -8.59 ± 1.11 | -4.01 | -2.79 |
| 2B | -1.46 ± 1.04 | -3.02 ± 1.34 | -1.56 | -0.92 |
| 3B | -1.86 ± 1.12 | -0.65 ± 1.54 | +1.21 | +0.64 |
| SS | 8.86 ± 1.20 | 3.00 ± 1.46 | -5.85 | -3.09 |
| LF | -6.40 ± 1.00 | -0.76 ± 1.22 | +5.64 | +3.58 |
| CF | 9.16 ± 1.28 | 10.06 ± 2.05 | +0.90 | +0.37 |
| RF | -3.71 ± 0.98 | -0.05 ± 1.18 | +3.66 | +2.39 |

Sum of z squared: 37.2 on 6 degrees of freedom (SSB boundary). The control, SSB 2041 against 2042,
both OOTP 26, gives 6.3. BLM 2057 against 2058 gives 10.6: LF +3.84 (z 2.07), 2B -2.98 (z -1.78), the rest
under 1.2. LF rising and SS falling hold in both leagues; 1B and RF do not.

Consequence for the blend: the half-weight turns a defence-half shift into half that shift in
posAdj (LF +2.8, SS -2.9, RF +1.8, 1B -2.0 runs for SSB if 2043 is used alone instead of
2041-42). Pooling the two engines therefore blends a stale defence value into the current one.
It is consistent with the memory that OOTP 27 changed corner-OF range; this audit does not test the mechanism.

Three windows are built for each league (`calib/BLM/pos_adj_multiyear*.json`, key `variants`):
all seasons pooled; current-engine seasons only; offence over all seasons with the defence half
from current-engine seasons only. Defence-half SEs by window are in the files (BLM 2058 alone:
1.03-1.48 per position; 2057+2058: 0.82-1.03; SSB 2043 alone: 1.11-2.05; 2041-43: 0.69-1.14).
In posAdj terms the SE is about half of these (the weight on the defence half).

## 5. Candidates and impact in wins

Impact = (candidate P minus the P the engine writes today) / 10.036 RPW, wins per player-season at
that position. The engine writes BLM's P for both leagues. Best Pos changes use his rule
(argmax of WAA wtd over eligible positions and DH) on the committed `hitters.json`, with each
hitter's WAA shifted by the P change at each position. Full table: output section 8.

BLM (460 MLB hitters, 6,545 in all levels):

| candidate | C | 1B | 2B | 3B | SS | LF | CF | RF | DH | MLB Best Pos changes | mean Max WAA change |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ours as published | +0.64 | -0.82 | -0.02 | -0.05 | +0.27 | -0.46 | +0.29 | -0.24 | -0.63 | 57 (12.4%) | -0.20 |
| ours restated | +0.14 | -0.59 | +0.03 | -0.04 | +0.10 | -0.31 | +0.20 | -0.13 | -0.40 | 47 (10.2%) | -0.18 |
| this tool, 2058 only | -0.06 | -0.24 | -0.30 | -0.25 | -0.19 | +0.19 | +0.30 | -0.02 | -0.07 | 18 (3.9%) | -0.08 |
| this tool, 2057+2058 | -0.09 | -0.36 | -0.18 | -0.19 | -0.19 | +0.08 | +0.32 | +0.04 | -0.17 | 19 (4.1%) | -0.11 |
| offence 2057-58, defence 2058 only | -0.09 | -0.33 | -0.25 | -0.23 | -0.22 | +0.17 | +0.36 | +0.02 | -0.14 | 17 (3.7%) | -0.10 |

Candidate P values (engine basis), BLM 2057+2058: C 8.72, 1B -8.46, 2B -3.98, 3B -2.06, SS 5.05,
LF -2.97, CF 5.35, RF -3.39, DH -8.46. Against the dashboard's 41-season history restated
(11.04, -10.78, -1.89, -0.58, 7.90, -6.91, 4.20, -5.10, -10.78) the two-season candidate is 0.2 to
3.9 runs apart: LF +3.94 is the largest. The disk cannot separate a 27-engine shift from a two-season draw
for BLM; SSB's test in section 4 says the shift is real for the defence half.

SSB (475 MLB hitters, 6,866 in all levels), against BLM's P as written today:

| candidate | C | 1B | 2B | 3B | SS | LF | CF | RF | DH | MLB Best Pos changes |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ours as published | +1.13 | -0.75 | +0.18 | -0.08 | +0.35 | -0.82 | +0.02 | -0.43 | -0.62 | 80 (16.8%) |
| ours restated | +0.47 | -0.53 | +0.19 | -0.06 | +0.16 | -0.61 | -0.03 | -0.29 | -0.39 | 64 (13.5%) |
| this tool, 2043 only | +0.21 | -0.44 | +0.05 | -0.10 | -0.28 | -0.32 | +0.06 | +0.18 | -0.39 | 86 (18.1%) |
| this tool, 2041-2043 | +0.33 | -0.42 | +0.14 | -0.07 | -0.06 | -0.55 | 0.00 | -0.02 | -0.44 | 89 (18.7%) |
| offence 2041-43, defence 2043 only | +0.33 | -0.53 | +0.10 | -0.04 | -0.21 | -0.40 | +0.01 | +0.07 | -0.44 | 88 (18.5%) |

Candidate P values (engine basis), SSB 2041-2043: C 12.96, 1B -9.11, 2B -0.69, 3B -0.92, SS 6.32,
LF -9.30, CF 2.11, RF -3.96, DH -11.23. Against the dashboard's SSB literal restated
(14.40, -10.21, -0.25, -0.82, 8.56, -9.88, 1.89, -6.67, -10.70) the largest gaps are RF +2.71 and SS -2.24.
SSB's CF is negative in every single-season offence-only estimate (-4.4, -1.8, -1.6 for 2041-43) and
positive only because the defence half is added; the dashboard's frozen SSB CF (2.3) has the same origin.

## 6. Flags and their resolution

| Flag | Resolution |
|---|---|
| F1 Units: dashboard posAdj per 1458 IP added to RunsP per 1200 IP | Verified by reading. Restated candidates are in sections 3 and 5. Fixing the dashboard is outside this repo; recorded here. |
| F2 Fork's SSB uses BLM's P | Measured in section 5. Needs the decision in 7.9. |
| F3 Frozen literals are OOTP-26-only | Measured in section 4. Resolved by the window decision 7.3. |
| F4 SSB `fielding_ratings.csv` for 2042 and 2043 includes minor leaguers (987 and 949 rows against about 500 MLB hitters) | Using it for total innings inflates m2 to 2.09-2.11 and DH innings by 50%. The loader sums the MLB-only position files instead (m2 1.853-1.879). Verified by running both. |
| F5 His RF branch-test quirk and thirds-notation divisor | Reproduced faithfully. Switching either off changes any position by under 0.0001 and 0.006 runs. No decision needed. |
| F6 His `pos_adj_calc` keeps pitchers' PA | BLM 2058 has 5 such players, 1,022 of 183,422 PA (0.6%). Left as his. |
| F7 ZR scale versus engine run values | Unresolved by data on disk; depends on Row 2. If the defence half were scaled to the 0.75/0.90 out values (IF x1.5, OF x1.36), BLM 2057+58 moves 1B -8.46 to -10.38, CF 5.35 to 7.17, SS 5.05 to 6.64; if scaled the other way (x0.667/x0.733), 1B -7.16, CF 4.02, SS 4.00. A swing of about 2 runs. |
| F8 Switcher SEs ignore player clustering | Stated; the control test (6.3 on 6 degrees of freedom) shows the SEs are not badly understated. |
| F9 Dashboard defence-only spectrum is per 1458 IP | Same unit issue as F1; section 4 of `best_pos.md`. |
| F10 Only 2 BLM and 3 SSB seasons are on disk | The tool takes any number; `Bank Season.bat` banks one actuals folder per season, so the window fills over time. A BLM multi-year blend beyond 2057-58 would need more `fetch_actuals.py` pulls (network, not run). |

## 7. Decisions for you

Each lists the options, the evidence, and my recommendation.

1. **Basis of the written values.** (a) engine basis, 1200 IP, catcher 1000 IP; (b) the
   dashboard's 162-game basis. Evidence: F1 and section 3. Recommendation: (a), because the
   values are added to RunsP on that basis. Whether to fix the dashboard's own 21.5% over-spread is a separate
   decision for that repo.
2. **Windows (H_def 5 / cut 20, H_off 2.5 / cut 8).** The cuts do not bind with 2-3 seasons;
   only the half-lives matter. Recommendation: keep the defaults and revisit when a league has
   about eight current-engine seasons.
3. **Engine boundary.** (a) pool all seasons; (b) current-engine only; (c) offence over all
   seasons, defence from current-engine seasons only. Evidence: section 4. SSB's defence-half shift (up to 5.9 runs) is larger than the
   one-season SE (1.1-2.1), so pooling carries a bias bigger than the noise it removes; the offence half has no
   such test. Recommendation: (c) until a league has three current-engine seasons, then (b).
4. **Half-and-half weight.** Defence-half SEs (0.8-1.1 pooled) are of the same size as the
   offence half's season-to-season spread (1.4-3.0), so 0.5 is not contradicted. Recommendation: keep 0.5.
5. **DH rule.** (a) DH tied to the lowest position (dashboard); (b) his offence-based DH value. For BLM 2057+58, (a) gives -8.46
   against his -6.80, a -0.17 win change for DH. Recommendation: (a) only if his Best Pos is meant to keep DH
   below 1B for equal bats; this is a design choice, not a data question.
6. **Centring.** Field-8 mean 0 shifts every position by -0.74 runs (BLM 2058) and lowers every hitter's WAA by about 0.07 wins
   against pitchers. Recommendation: apply it only together with the WAR replacement level decisions of Phase 1.
7. **LF and RF.** Split or pooled. Blended BLM 2057+58 LF/RF differ by 0.4 runs (0.04 wins), so the choice changes
   Best Pos for 1 MLB hitter (19 against 20). Recommendation: pooled, matching his engine, because the
   split carries 0.4 runs of noise.
8. **Catcher and DH from offence only.** Unchanged from the dashboard; the dashboard shelved
   catcher corrections of +1.7 to +2.3 runs and Bayesian shrinkage. Recommendation: no change now.
9. **SSB's own P.** Replace BLM's P with an SSB-specific set, using decision 3's window. Evidence: section 5; the SSB candidate differs
   from BLM's P by up to 0.55 wins (LF -0.55, 1B -0.42, C +0.33). Recommendation: yes, because SSB's
   fielding and offence spectrum differ from BLM's (SSB LF is -9.3 against BLM -3.0).
10. **Wiring.** When any set is approved, add its `P2..P10` as an overlay on `metadata-latest.json`'s `pos_adj`
    group (one assignment per cell in `metadata_calibrate.OUTPUTS`); no engine edit is made now.

## 8. What was built and what is not verified

Files: `tgs-viz/engine/pos_adj_multiyear.py` (numpy and stdlib only), `tgs-viz/engine/calib/BLM/pos_adj_multiyear.json`
and `pos_adj_multiyear_SSB.json` (gated candidates), `tgs-viz/tools/tests/test_pos_adj_multiyear.py`
(24 tests), `docs/phase2/pos_adj_audit.py` with its output, `pos_adj_ours_repro.py` with its output.
No engine, ingest, app or data file of his was edited. A test asserts that no module reads the candidate file.

Run: `python tgs-viz/engine/pos_adj_multiyear.py --league BLM --season 2058=tgs-viz/engine/calib/BLM/metadata_inputs --season 2057=tgs-viz/backtest/actuals/BLM/2057 --league-id 144 --engine-first-season 2058 --se 500 --out <file>`.

Verified by running: his P reproduced; ours reproduced; the tool's defence half equals the dashboard's;
every table above. Inferred, not run: the unit mismatch's effect on the live dashboard (read from code, not
re-run end to end), the mechanism behind the 26-to-27 shift, and the ZR scale (F7). Blocked: BLM
history beyond 2057-58 needs more actuals pulls (network); the SSB 2043 season is the only current-engine SSB season.
The SSB inputs are read from the dashboard checkout (`OOTP_DASHBOARD`), not from the fork.
