# Phase 2 status: model merge

*2026-10-03, branch `phase2-model` (built on `phase1-war`). Rows refer to the Phase 2 table of
ootp-dashboard `docs/migration-plan:docs/MIGRATION_PLAN.md` §3. Every row has an audit in
`docs/phase2/`. **No production number has changed**: value-changing work is gated (a patch in
`docs/phase2/`, a flag that is off, or a calib file nothing reads). Six parallel work streams did
the audits and builds; the numbers marked "rechecked" were reproduced again on the merged branch.*

## Where each row stands

| # | Item | State | Audit |
|---|---|---|---|
| 1 | Positional adjustments | Built, gated: `engine/pos_adj_multiyear.py`, candidates in `calib/BLM/pos_adj_multiyear*.json` (unread) | `pos_adj.md` |
| 2 | Fielding out-values | Built, gated: `engine/out_values.py`, `out_values.patch` (`--derived-out-values`, off) | `out_values.md` |
| 3 | Eligibility floors | Gated patch `eligibility_corner_of_45.patch`; tool `tools/eligibility_usage.py` | `eligibility.md` |
| 4 | bestPos Option B | Inputs computed; `option_b_best_pos()` built; Best Pos WAR waits on Phase 1 | `best_pos.md` |
| 5 | OOTP-27 curves | Harness built, gated: `engine/pw_curves.py`, `curve_bakeoff.py`, `promote_scurves --three-way` | `curves.md` |
| 6 | Baserunning | Audited; gated patch `baserunning_ubr_centered.patch` | `baserunning.md` |
| 7, 8, 9, 13 | Adopt his | Verified present in his engine; logged | `adopted.md` |
| 10 | Fielding referee | **Wired** (tooling): `backtest/referee_fielding.py` | `fielding_referee.md` |
| 11 | Per-league validation | **Wired**: `doctor.py --deep` (`tools/doctor_deep.py`); default doctor output byte-identical | `validation.md` |
| 12 | Engine-version boundary | **Wired**: optional `engine_first_season`; `metadata_inputs.py` refuses earlier seasons before any request | `engine_boundary.md` |
| 14 | Slot shares | Measured; gated patch `slot_shares_wiring.patch` | `slot_shares.md` |

Tests: the tools suite is 227 tests on the merged branch, all passing (was 109 at `macos-baseline`).
His sheet validators (`hitters.py` / `pitchers.py` main, `build_json.py`, `ratings.py --selftest`)
report mismatches **identically on his untouched `upstream/main`** on this Mac ("CHECK, worst
1.93e+01"), so they are pre-existing, not caused here. Not checked on Windows.

## Findings worth knowing before deciding

- **Curves (row 5).** As wired, our piecewise curves beat his by the 5% margin on no pitching
  block, on either real OOTP 27 season on disk (BLM 2058, SSB 2043). The loss is the substrate and
  knot placement, not the family: refit on his archive's bucket means, our family scores 0.428 vs
  his S-curve 0.420 and two-line 0.464. A real test needs his clone-sim CSVs.
- **Fielding referee (row 10).** Slope of real range runs on the engine's range channel (1.0 = the
  curve moves runs as fast as the real league): infield ≈ 1 (2B 0.97, SS 0.97 pooled); **LF 0.52 on
  BLM 2058 (rechecked: 0.523 ± 0.155) and 0.54 on SSB 2043** — the LF curve is about twice as steep
  as reality; CF's top end looks over-credited.
- **Out-values (row 2).** Derived from linear weights: inf_out 0.7013, of_out 0.8341 (rechecked) vs
  hand-entered 0.75 / 0.90; replicates on SSB 2043 (0.7015 / 0.8295). Zone identity: derived 0.980,
  hand-entered 1.055. If wired: BLM MLB mean −0.034 WAA, largest −0.18, 2 of 460 change Best Pos.
- **Positional adjustments (row 1).** His BLM set re-derives exactly. The plan's large gap (C 6.5,
  1B 8 runs) is mostly **a unit bug in our dashboard**: its frozen spectrum is runs per 162 games
  (1458 innings) added to fielding runs per 1200 innings with no rescale — 21.5% too wide, 45.8% at
  catcher (code read and confirmed; the 1458 basis of the research grid is the agent's
  reproduction). Restated, the BLM gap at C is 1.4 runs. The ZR-switcher defence values shift
  across the OOTP 26→27 boundary (SSB χ² 37.2 on 6 df vs 6.3 for a 26-vs-26 control).
- **Eligibility (row 3).** His corner-OF floor of 50 excludes 12.5% (LF) / 7.6% (RF) of real
  innings in BLM+SSB; 45 excludes 2.7% / 0.9%. Changing it changes no Best Pos or Max WAA in any
  league. Our SS TDP ≥ 45 floor would strip real shortstops (one with 862 SS innings); our 1B
  ERR > 20 floor excludes no real 1B.
- **Baserunning (row 6).** Our UBR line has the sign bug his B9 fixed (+0.5 runs / 600 PA phantom
  credit); our OOTP-26 SBA intercept is sign-wrong (league attempts +31% to +52%). His steal model
  is within 2.4% of real league attempts — nothing to port.
- **Phase 1 input.** BLM's real 2057 season gives runs-per-win 8.858 (geometric mean of the two OLS
  directions, 30 clubs; rechecked) vs his 7-clone fit 10.036. One season cannot overturn the
  archive fit; it is evidence for the pending currency decision.
- **App bug (for the app phase).** The Positional Strength / standings pages have no club list for
  SSB (`LEAGUE_TEAMS`, `pages/TeamStandingsPage.jsx:14`), so SSB's board ranks 50 clubs incl. 22
  foreign ones at replacement level.

## Decisions (yours)

| Row | Decision | Recommendation |
|---|---|---|
| 1 | Engine-boundary rule for the blend | Offence over all seasons, defence from current-engine seasons only, until a league has 3 OOTP 27 seasons |
| 1 | DH rule (tie to lowest vs offence-based) | No recommendation — no data referee |
| 1 | Centring (field-8 mean 0, ≈ −0.07 wins per hitter) | Decide together with Phase 1 replacement level |
| 1 | SSB-specific positional adjustments | Yes (SSB's own differs from BLM's by up to 0.55 wins at LF) |
| 2 | Out-values | Derived per league at the next Recalibrate (`out_values.patch`) |
| 3 | Corner-OF floor | 45 for BLM-basis leagues, TGS stays 50; don't import our SS/1B floors |
| 4 | RF arm threshold | MLB-deployed RF mean (BLM 62.35 = his `I43`, SSB 61.72), not our 55.2 |
| 4 | Best Pos target | Keep his; Option B as a second column if wanted |
| 5 | Piecewise curves | Don't wire; refit our family on his archive when his CSVs arrive |
| 6 | UBR frame | Centred (`baserunning_ubr_centered.patch`), +0.03 wins per hitter |
| 10 | Wire the referee into the post-season flow | Yes, after Bank Season |
| 12 | `engine_first_season`: SSB 2043; BLM 2058? | SSB yes; BLM only once 2058 is confirmed (it blocks rebuilding 2051–57) |
| 14 | Slot weights on the strength board | Don't wire as a correction (rank correlation 0.95–1.00 with today) |

## Blocked

- **His clone-sim archives** (`engine/calib/<LG>/*.csv`): fitting our curve family on his
  substrate, re-running the fielding-curve gate in the 45–50 band, testing out-values in the sim.
- **Network (needs your OK)**: more BLM seasons (multi-year posAdj on BLM), an out-of-sample BLM
  2059 season, SSB metadata via `metadata_inputs.py`.
- **Phase 1 decisions**: Best Pos WAR, centring.
