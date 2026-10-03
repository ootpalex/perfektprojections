# Phase 2, rows 7, 8, 9, 13: "adopt his" audit log

Audit log the migration plan asks for. For each item: does it exist in his engine at the fork's head
(`43ed272`), is it live or gated, does ours (ootp-dashboard `8c6337a`) hold anything his lacks, and what differs
from what the plan says. No code was written for these rows. Every file:line below was opened this session;
numbers marked "run" were computed this session, the rest were read from files.

## 1. What this means for you

- **All four items exist in his engine and can be adopted as the plan says. Ours has nothing for rows 7, 8 and 13 that his lacks,** with
  one exception to decide: ours recomputes runs-per-win from the live league each build, his freezes a fitted value (section 3).
- **The plan is wrong on two facts in row 7.** The currency layer is live in production for both leagues, not gated. The BLM fitted
  RA/9 exponent is 2.183 for starters and 2.232 for relievers, not 2.28 (2.276 is TGS relievers).
- **Both bugs in row 9 are still present in ours at its current head** (B5 at `regressions.py:1102` and `hitters.py:652/674/691`,
  B8 at `hitters.py:871-872`), and both are fixed in his engine. I confirmed B8 is live in his BLM output by reproducing a catcher's WAA to 5 digits (run).
- **One drift to fix on his side, not mine:** the app's hand-copied BLM workload constants no longer match the 2026-10-01 refit
  (starter workload 0.930 versus fitted 0.922; reliever 0.990 versus 0.982). A one-season real check also puts BLM's runs-per-win below the fitted value (section 3).

## 2. Plan drift found (the plan was written against his `e9aca96` and ours `218dd86`)

| Plan says | Head says |
|---|---|
| Row 7: exponent "2.28 BLM"; currency "all gated" | BLM SP 2.183 +- 0.011 (n = 1,780 pitcher-seasons), RP 2.232 +- 0.016 (n = 2,444); TGS SP 2.197, RP 2.276. Live for both leagues (`ratings.py:288-301`, section 3). |
| Row 7: ours `pitchers.py:440` exponent 2.0 | Still there at `pitchers.py:440` and `:452`. |
| Row 6: his B9 fix at `hitters.py` ~253-262 | Now `hitters.py:280-290` (B1 at 273-279, the SB% cap at 252-268). Covered in `baserunning.md`. |
| Row 9: ours `hitters.py:652` applies E% per play; `hitters.py:871` adds 600-PA BSR to 500-PA batting | Same lines at head (`:652`, `:871-872`). `regressions.py:1100` is now `:1102`. |
| Row 9: his B5 refit at `calibrate.py:518-548` | Same lines (comment 518, loop 525-548). |
| Row 13: ours `ballparks.py:269-284` | Same lines (`_mean_factors` at 269; used at 521). |

## 3. Row 7: currency (fitted RA/9 exponent, runs-per-win, luck SD, workloads)

**Exists, live, adoptable.** Terms: **RA/9** is runs allowed per nine innings. **RPW** is runs per win. **Luck SD** is the standard
deviation of a team's win total for fixed talent. **Workload** is the share of the model's assumed innings that the sim actually gives the
top-5 starters (or top-8 relievers).

| Piece | His implementation | Live status | Value (BLM / TGS) |
|---|---|---|---|
| wOBA-against to RA/9 exponent, per role | `engine/currency_fit.py:180` `fit_exponents` (log-log fit on archive pitcher-seasons); applied `engine/pitchers.py:303-304`, `:454`, `:501`, `:582` | Live: `ingest/ratings.py:288-301` `live_currency`, passed at `ratings.py:496-499`, `refresh.py:425`, `draft.py:327,467`, `export_league.py:269-271` | SP 2.183, RP 2.232 / SP 2.197, RP 2.276 |
| RPW | `currency_fit.py:260-291` `fit_wins` (geometric mean of the two regression directions); overrides workbook `H30` at `engine/hitters.py:146-149` and `pitchers.py:299-302` | Live (same wiring) | 10.036 (directions 10.400 and 9.686) / 10.651 (10.828 and 10.476) |
| Luck SD | `currency_fit.py:296`; consumed by the app only (`src/lib/leagueCalib.js:80,109`) | Live in the JS win models | 6.37 wins / 6.98 |
| Workloads | `currency_fit.py:~300-312`; consumed by `rosterOptimizer.js:1424-1429` | Live in the JS | SP 0.922, RP 0.982 / SP 0.942, RP 0.957 |

Verified by running: his committed BLM `hitters.json` uses the fitted RPW. For the first BLM row, a catcher, `C WAA vR` recomputed
from the row's `C RunsP`, `BSR vR`, `wOBA vR` and the workbook constants gives -3.40115 at `H30 = 10.036` and -3.60653 at the workbook's
`H30 = 9.4645`; the file says -3.40115.

**Ours.** The exponent is a literal 2 (`pitchers.py:440`, `:452`). RPW is `lg_RA/9 x 1.5 + 3` computed from the league's own pitching
data on every build (`aggregators/_shared.py:17-27`). There is no luck SD, workload, or fitted run-value layer.

**What ours has that his lacks:** the live recomputation. His 10.036 is a constant from the clone archive; his workbook `H30` (9.4645 for
the 2058 BLM metadata) tracks the live league but is overridden. If the run environment moves, his value does not. This is a Phase 1 (WAR currency)
question, not a port: do not copy ours, but the fit would need re-running when the environment changes.

**Flags, with resolution:**

1. **The app's BLM constants are stale against the fit.** `leagueCalib.js:110-111` has 0.930 / 0.990; `currency.json` (fitted 2026-10-01) has 0.922 / 0.982. TGS
   matches (0.942 / 0.957). RPW and luck SD match for both. Starter workload is 0.9% high and reliever workload 0.8% high in the app.
   Resolution: the file header says to re-mirror after each fit; this is a pending mirror, not a design problem. Left for his side.
2. **Luck SD is fitted on 154-game archive seasons and applied to 162-game live seasons.** `currency.json` for BLM has `games = 154`; the banked 2057 season has
   every club at exactly 162 games (30 clubs, 2,430 wins, 2,430 losses; run). A win total's spread scales with the square root of games, so 6.37 would
   be about 6.53 (+2.6%). This is inferred from binomial scaling, not run against the archive. RPW is per run, so it does not scale.
3. **A real-season cross-check puts BLM's RPW below the fitted value** (run, BLM 2057 actuals, 30 teams, split 1 level 1): regressing
   wins-above-81 on run difference gives 9.37 in one direction and 8.37 in the other, geometric mean 8.86 (team-resample bootstrap SE 0.47 over 2,000 resamples,
   correlation 0.945). The fitted 10.036 is 2.5 SE above that one season; the live tangent 9.46 is 1.3 SE above. One season of 30 teams cannot overturn a
   7-clone archive fit. I record it as evidence for the pending Phase 1 RPW decision, not as a verdict.

## 4. Row 8: level transport (Jensen), split-aware potentials, measured role-stuff shift

### 4.1 Level transport

The plan calls this "Jensen". The term: a curve that bends gives a different average over the league's players than its value at the
average rating (the Jensen gap). **Level transport** moves a fitted curve to the live league by subtracting the curve's average over the live
players and adding the live league's actual rate, so the league mean is reproduced exactly.

| Piece | His implementation | Live status |
|---|---|---|
| Pitching rate curves | `engine/scurve_fit.py:3-5, 15-20` (method), `:700-711` (exact-mean renormalisation `offset = league rate - E_live[f]`, and the same level step for the two-segment line) | Live per block: `calib/BLM/scurves.json` and `calib/TGS/scurves.json` exist; `pitchers.py:85-104` reads the per-block `twoline_offsets` |
| Fielding range to plays-made | `engine/fielding_curves_fit.py:24-33, ~291` (offset = live position population's innings-weighted mean); applied `engine/hitters.py:158-163` `pm_pw`, `:306-348` | Live: `calib/BLM/fielding_curves.json` and `calib/TGS/fielding_curves.json`; positions 1B 2B 3B SS LF CF RF; `ratings.py:266` |
| Hitting two-line rate blocks | Anchored at the live league mean ratings (workbook `H2`-`H10`), no Jensen correction. Archive tail corrections: `engine/hitter_tails_fit.py`, `hitters.py:109-125` | Live: `live_hitter_tails` (`ratings.py:256`) |

**Ours** has two such corrections: `_with_centred_fielding_consts` (`metadata.py:866`) for nine fielding channels and `_with_league_adaptive_sba_c0`
(`metadata.py:809`). His fielding offsets cover seven positions (all but catcher). Ours also lists the catcher framing and arm channels, but
those are linear terms, where the correction is exactly zero (stated in `metadata.py` at the comment on linear terms), so nothing is missing. Ours' SBA correction is audited in `baserunning.md`
(not worth porting). Ours' continuous multi-knot hitting curves are row 5, not this row.

**Verdict: adopt his; nothing to port.** Plan accurate.

### 4.2 Split-aware potentials

OOTP publishes potential without platoon splits. His engine rebuilds splits around the published potential, keeping the player's own current
lean (`vR - vL`).

- Hitters: `engine/hitters.py:424-481`. Peak vR = P + (1 - s) x lean, peak vL = P - s x lean, where s is the batting-hand platoon share
  (`H24`, `H23`, `H25`); the cap is `max(80, current vR, current vL, P)` (`:458`). Measured on 30+-year-old hitters with at least a 5-point split: published potential equals the
  blend rounded to 5 in 77% of TGS and 75% of BLM cases, against 73% and 65% for "equals vR" (comment at `:426-433`, not re-run).
- Pitchers: `engine/pitchers.py:540-556` onward, measured on 28+ pitchers (n = 911 lean-vR, 396 lean-vL).
- Live: both feed the P columns in `run_hitters` and `run_pitchers`.

**Ours** (`export.py:143-165`): `_HITTER_POTENTIAL_MAP` and `_PITCHER_POTENTIAL_MAP` copy the one potential number into both the vR and vL columns of a prospect
copy, so a split hitter is priced as flat against both hands. Nothing in ours is absent from his. **Verdict: adopt his.**

### 4.3 Measured role-stuff shift

His engine moves a pitcher's Stuff by his own expected gain between the starter and reliever roles instead of a flat 5.

- Fit: `engine/role_stuff_fit.py` (module docstring `:1-47`); output `calib/<LG>/role_stuff.json` (BLM version 2, dated 2026-09-26). Archive evidence: reliever
  stuff equals starter stuff 51% of the time (TGS, 2,211 switches) and 60% (BLM, 1,433) and is one notch (5 points) higher the rest of the time; average gain +2.5 (TGS) and +2.1 (BLM).
- Applied: `engine/pitchers.py:117-185` (model), `:255-266` and `:316-329` (gain lookup, observed switches first), `:405` (replaces the flat 5).
- Live: `ingest/ratings.py:277` `live_role_stuff`, passed at `ratings.py:496`, `refresh.py:444-450`, `draft.py:344,479`, `export_league.py:272`.

**Ours** (`pitchers.py:296-306`): non-SP position gets Stuff - 5 in the SP section, and +5 in the RP section for the threshold and high branch; flat. Nothing
in ours is absent from his. **Verdict: adopt his.**

## 5. Row 9: bugs in ours that his engine fixed

### B5: infield error rate fitted per inning, applied per play made

- **Ours, still present.** `regressions.py:1101-1103` fits infield E% as errors per inning (`_fielding_err_rate_ip`, `:701`). `hitters.py:652` (2B), `:674` (3B) and `:691` (SS) multiply
  that slope by plays made (`PMAA + PA x lg_pm`).
- **Size (run, SSB 2043 `fielding_data_<pos>.csv`, summed over the league):** plays made per inning is 0.296 (2B), 0.283 (3B), 0.322 (SS). A slope fitted per inning and applied per play is
  therefore compressed by a factor of 3.38 (2B), 3.54 (3B), 3.11 (SS) (plays made = sum of the five `BIZ-?m` columns, the same definition as our `_BIZ_MADE`).
- **His fix.** `engine/calibrate.py:518-548`: 2B, 3B, SS fitted as errors per play made, with their own pivot's league total as the baseline; 1B stays per inning because the engine multiplies it by innings
  (`hitters.py:313`). The committed BLM constants show it: 2B/3B/SS E% slopes -0.00052 / -0.00072 / -0.00064 against -0.00008 for 1B (`constants-latest.json`).
- **Verdict: adopting his engine removes B5.** Confirmed; plan accurate.

### B8: catcher WAA adds a 600-PA baserunning total to a 500-PA batting total

- **Ours, still present.** `hitters.py:871-872`: `c_waa = (c_runsp + bsr + batr_c + park_adj_c + pos_c) / waa_const`, where `bsr` is a 600-PA quantity and `batr_c` is built at
  `lg.pa_c` = 500.
- **Size (run, BLM `hitters.json`, 542 hitters with 2058 stats):** the error is `BSR x (1 - 500/600)`, one sixth of the hitter's BSR. BSR wtd runs from -6.45 to +10.28 per 600 PA
  (5th to 95th percentile: -5.35 to +6.26), so a catcher's WAA was off by -0.9 to +1.0 runs (-1.1 to +1.7 at the extremes) before the fix, or 0.09 to 0.10 wins at 10.036 runs per win.
- **His fix.** `engine/hitters.py:374-378` (`BSR * (H32 / PA)`), the same at `:415` (offence/defence split) and `:474-476` (potential line). Verified live by the catcher reproduction in section 3.
- **Verdict: adopting his engine removes B8.** Confirmed; plan accurate. The catcher DH line still uses `BSR x 0.98` in both (a separate sheet rule).

## 6. Row 13: parks

**Exists, live, adoptable.** Plan accurate on the substance; the effect of dropping ours is small.

- His rule: 50% of the home park plus 50% of the mean of the other parks, per outcome and batter hand. Built in `ingest/parks.py:110-126` (`blend[key] = 0.5 * home + 0.5 * mean(other parks)`),
  stored in `calib/<LG>/park_blend.json`, pushed through the workbook's own park chain by `engine/parklayer.py:75-130` (docstring `:24-28`: no extra halving).
  Two bases: Neutral (all factors 1, the shipped default) and the home-park blend; per-club values with an exact-delta gate at `ingest/park_values.py:115-207` (tolerance 1e-6 on field-position spread and on the platoon-weighted rule).
- Ours: the league row is the mean over every park including the home park (`ballparks.py:269-284`, used at `:521`), and the delta is `(team - league) x home_fraction` (`:612-655`).

Difference, derived and checked on BLM (run, `park_factors.csv`, 30 parks, home club Tampa Bay, 29 other parks): with N parks, `team - mean_all = (N-1)/N x (team - mean_others)`, so ours shrinks the
home effect by a factor of 29/30 (3.3%) relative to his rule when the baseline is the other-park mean. His baseline is neutral (1.0), not the league mean (BLM league means run 0.995 to 1.018 across
outcomes). The home-park delta in factor units:

| Outcome | Ours: 0.5 x (home - mean of all 30) | His: blend - 1.0 |
|---|---|---|
| HR vs right-handed batters | -0.0292 | -0.0297 |
| Overall average | -0.0179 | -0.0215 |

The gaps (0.0005 and 0.0036 in factor units) are below the spread between parks (HR RHB 0.74 to 1.27). **Verdict: adopt his; drop ours.** Nothing in ours is absent from his.

## 7. Open items for you

1. **Re-mirror the BLM workloads** in `src/lib/leagueCalib.js:110-111` from the 2026-10-01 fit (his files; flagged, not edited).
2. **Luck SD and games** (section 3, flag 2): decide whether to refit BLM on a 162-game basis or scale by sqrt(162/154).
3. **RPW** (section 3, flag 3): the one-season real check argues for a lower RPW than 10.036; this belongs to the pending Phase 1 currency decision.

## 8. Verified by running, and not

Run this session: the catcher reproduction (section 3), the SSB plays-per-inning ratios (section 5), the BLM real-season RPW regression and bootstrap (section 3), the 2057 game-count check (section 3), the BLM park-factor arithmetic (section 6),
and the `currency.json` values for both leagues. Read from files, not run: all file:line citations and the descriptions of what each piece does; the quoted archive statistics in the engine's own comments (hitter potential 77%/75%, role-stuff 51%/60%); the claim that
no code path in ours implements any of these; the whole of row 13's effect on valuation (no dollar or WAA impact was computed).
His validators and tools tests were not run: no engine or tool file changed.
