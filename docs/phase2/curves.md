# Phase 2 row 5: rating-to-rate curves, three-way bake-off

*2026-10-03, branch `phase2/curves` off `phase2-model` (his `9dadf36` + Phase 0/1 commits). Audit
first, code second, results last. Tags: 🟢 computed from real data · 🟡 borrowed constant ·
🔵 deliberate assumption. Each claim is marked **verified** (read or run this session) or
**inferred**.*

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

*(Sections 2 onward are filled in as the work is done.)*
