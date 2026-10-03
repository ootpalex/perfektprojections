# Phase 1 audit: WAR as the single currency

*2026-10-02, fork `phase1-war` off `macos-baseline` (his `9dadf36` + Phase 0). Audits the plan in
ootp-dashboard `docs/migration-plan:docs/MIGRATION_PLAN.md` §2 before any code. Inputs are tagged
🟢 computed from real data · 🟡 borrowed constant · 🔵 deliberate assumption. Each claim says
whether it was **verified** (read or recomputed this session) or **inferred**. Three read-only
audit passes produced the raw findings; the numbers marked "rechecked" were recomputed again by
hand.*

## 0. Findings that change the plan

1. **The app prices SSB (and RG) on TGS's constants.** `leagueCalib(league)` returns TGS for any id
   it does not know (`src/lib/leagueCalib.js:162`). SSB and RG are BLM-basis in the engine, but the
   app gives them TGS's RPW, workloads, luck SD and replacement offsets (market hitter 1.65 /
   SP 2.5 / RP 0.45 instead of BLM's 1.91 / 2.5 / 0.31). **Verified** (read, rechecked). Fix
   first: resolve by the manifest's `basis`.
2. **The replacement block should not go in `currency.json`.** `currency.json` is one of the six
   files hashed into the calibration fingerprint (`backtest/ml/common.py:1040`,
   `engine/agecurve_fit.py:146`, `backtest/dev_odds.py:374`). Editing it invalidates every
   `.waa_cache` and every DEV price tag. WAR = WAA + a constant, so the WAA caches stay valid if
   the block lives in its own file. **Verified** (read, rechecked).
3. **Swingman count is 691, not ~330.** Pitchers whose role flips between max(SP WAA, RP WAA) and
   max(SP WAA + 2.5, RP WAA + 0.31): 691 of 5,079 BLM pitchers with both roles, 146 of 296 at MLB.
   Every flip is RP → SP. On potential (`WAP` / `WAP RP`) it is 2,599. **Verified** (recomputed,
   rechecked). The plan's figure does not reproduce on any population tried.
4. **Catcher argmax barely moves.** With the catcher credit at 500/600 of the hitter credit, 0 of
   63 BLM MLB Best-Pos-C bats leave C (2 of 61 for TGS). The over-credit itself is 1/6 of the
   hitter credit: **0.32 wins** at BLM's 1.91 (0.28 at TGS's 1.65). **Verified** (recomputed).
5. **Several app sites the plan missed** (§3): a durability scaler that would silently skip a
   `WAR` column, a market-offset site in `usePlayerData.js`, a second WAA colour ladder applied to
   WAR values on the Market page, the dev-odds bars, and WAA gates in `orgBuilder.js`,
   `MockDraftPage.jsx` and `PlayerTable.jsx`. **Verified** (read).

## 1. His WAA (engine) — plan §2a

| Role | Definition at head | Basis | Tag |
|---|---|---|---|
| Hitter | `(rp[pos] + BSR + BatR + PosAdj)/H30`, `engine/hitters.py:380`; DH `:381` | 600 PA (`H31`, `:168`) | 🟢 curves, 🔵 basis |
| Catcher | bat, park and BSR scaled to `H32`; defence `rp["C"]` and `W2` not scaled, `hitters.py:377-378` (audit B8) | 500 PA (`H32`) | 🔵 |
| SP | `((H41 − RA9)·H33/9)/H30`, `pitchers.py:~483, 510` | 800 BF = H33 IP | 🟢 |
| RP | same vs RP league RA/9 `H42`, `pitchers.py:538` | 300 BF = H34 IP | 🟢 |

Pitcher cells (`engine/extracted/<LG>_pitchers_datapoints.json`): BLM H33 = 188.65 IP,
H34 = 70.74 IP; TGS 185.81 / 69.68. **The same cell names mean different things in the hitter
sheet** (H33/H34 = 1200/1000 fielding innings there), so a replacement block must not key on bare
cell names. **Verified** (read).

**RPW** (`H30`) is fitted in `engine/currency_fit.py:260-314` as the geometric mean of the two OLS
directions (W on RD, RD on W), written at `:402, 410-411`. BLM 10.036 (pair 10.40 / 9.686; workbook
9.4645), TGS 10.651 (workbook 10.081). 🟢. Reaches the engine through
`ingest/ratings.py:300 live_currency` → `hitters.compute` / `pitchers.compute` overlay
(`hitters.py:146-149`, `pitchers.py:299-303`). The sheet-fidelity validators never pass currency.
**Verified** (read).

## 2. Replacement level — plan §2a, §2b item 4

Shipped in `src/lib/leagueCalib.js` (unchanged since e9aca96), wins added to WAA at the bases above:

| League | Market hitter / SP / RP | Org hitter / SP / RP |
|---|---|---|
| BLM | 1.91 / 2.5 / 0.31 | 0.64 / 0.28 / 0.01 |
| TGS | 1.65 / 2.5 / 0.45 | 0.94 / 0.61 / 0.17 |

**Market** = median of up to three routes:

1. **Budget identity** on banked actuals 🟢. **Reproduced for BLM 2057** (league 144, level 1,
   split 1, stint 0; 30 clubs): batting WAR 19.146 per club over 10.013 hitter slots of 600 PA →
   **1.912** (rechecked); SP 11.70 per club over 4.43 slots of 800 BF → 2.643; RP 2.50 over 8.41
   slots of 300 BF → 0.298. Club total 33.35 WAR = a .294 replacement club (81 − 33.35 = 47.65 of
   162). 🔵 SP/RP split rule `gs ≥ g/2`: `gs ≥ 5` gives SP 2.425 / RP 0.282, `gs > 0` gives
   2.140 / 0.402. Club-bootstrap 95% intervals: hitter [1.57, 2.25], SP [2.30, 3.00], RP
   [0.16, 0.43] — these mostly measure club luck. 🔵 OOTP's own `war` carries OOTP's replacement
   convention, so this route measures OOTP's .294 club, not an independent market.
2. **Delivered-WAR regression** 🟢: hitter 2.059 [1.837, 2.278] n=204, SP 2.362 [2.138, 2.579]
   n=117, RP 0.313 [0.216, 0.409] n=194. **No code in the repo**; the numbers exist only as
   comments. Not re-run.
3. **Market pin** (hitter) 🟢: 1.815 [1.216, 2.466], n=30 FA signings. No code in the repo. Not
   re-run.

Shipped = medians: hitter median(1.912, 2.059, 1.815) = 1.912; SP mean(2.643, 2.362) = 2.50; RP
mean(0.298, 0.313) = 0.31. **Inferred** from the comment's numbers.

**Org** (`scripts/measure_replacement.mjs`): midpoint of the worst rostered and best non-rostered
player per org, from ratings projections only. Circular as a market measure; keep it only as the
optimizer's cut/keep parameter, as the plan says.

**Ours** 🟡 (FanGraphs; `model/src/data_points.py:36-51, 929`): 20 R / 600 PA ⇒ 1.99; 0.12 W/9 IP
⇒ SP 2.47; 0.03 W/9 IP ⇒ RP 0.23 (our IP bases). Retire, as planned.

**Units** — WAA is a rate at fixed playing time, so WAA + offset(role) is correct where the bases
match: hitter 600 PA ✓; SP 800 BF ≈ 189.9 IP vs H33 188.65 (0.7%) ✓; RP 300 BF ≈ 70.8 IP vs H34
70.74 ✓; **catcher ✗** (500 PA WAA, 600 PA offset → over-credit 1/6 of the offset).

### SSB

SSB has **no OOTP `war` column and no standings** anywhere on disk. ootp-dashboard
`leagues/SSB/metadata/{2041,2042,2043}` holds hitting/pitching/fielding lines (ID, ORG, G, PA, IP,
BF, …; no level, no team id). All three seasons complete (W = L = 2,268 ⇒ 28 clubs × 162 G,
inferred). Only **2043** is on the OOTP 27 engine (`engineFirstSeason["27"] = 2043`). 2042 has ~2×
the rows (minors included, no level column). The fork has no SSB actuals. Route 1 needs OOTP's
`war` per player with level/split/stint — what his `backtest/fetch_actuals.py` pulls from StatsPlus
(not run). Expected precision with one season: route 1 about BLM's width; route 2 about ±0.2
hitter/SP, ±0.1 RP. **Needs a decision (§4).**

## 3. App call sites — plan §2b items 5-8

Current line numbers (his head); ✗ = plan cite wrong/moved, ★ = missed by the plan.

**Offsets added to WAA**
- market: `marketValue.js:326-341 getPlayerWAR` (includes `Max WAA vR`, unlike futureValue);
  `futureValue.js:275-332 getPlayerWAAValues`; `draftFV.js:379-380` pitcher current leg ✗(376-379);
  ★`usePlayerData.js:829-836` pitcher age-percentile metric.
- org: `waivers.js:74-77, 103` ✗(73-86); `positionalStrength.js:209-216` and empty slots at
  `:122, 162`; `rosterOptimizer.js:1241-1250, 1388-1397` — **dead fields** `_war`, `_spWAR`,
  `_rpWAR` (no readers; the optimizer ranks and totals in WAA).
- scripts: `draft_inversions.mjs`, `draft_player.mjs`, `market_impact.mjs`, `market_report.mjs`,
  `control_window_report.mjs`.
- No catcher scaling anywhere in the app.

**Display-WAA track**: `futureValue.js:494-501 warTrack`, `:602-619`, `:~700-760`, `:893-905`;
`usePlayerData.js:700-790`; `PlayerDetail.jsx:444-479`. `draftFV.js:343-358` ceiling is plain WAA.

**Columns and colour**: `columns.js` groups and labels (:34-53, :812-848, :892); dead `'WAR wtd'`
at `columns.js:51, 838` and `PlayerDetail.jsx:412` ✗(393). Ladders: generic `columns.js:575-581`
(≥5/3/1.5/0/−1, matches any name containing WAA/WAR/WAP), `Dev_PeakP50` `:470-480`,
★`MarketValuePage.jsx:787-793` (≥3/1.5/0/−1 applied to WAR values today).

**Aging**: multiplicative `applyAging` (`futureValue.js:178-182`) and `agedWAR`
(`marketValue.js:1164-1170`) live only in the no-curve fallback and `DevAnalysisPage`; additive
`measuredPath` (`futureValue.js:362-387`) is the normal path.

**Workload**: `rosterOptimizer.js:1418-1429` scales `_spWAA`/`_rpWAA` only (BLM 0.930 / 0.990 in
the app vs 0.922 / 0.982 in BLM `currency.json` — **two values for one quantity**, verified read).

**WAA thresholds**: `orgBuilder.js:537` TRAIN_PEAK_BAR 0, `:488` NO_CHANCE_POT −1, `:499`
BAT_POT_OK −0.25, ★`:256-257, 478, 1520` pot > 0 / ≥ −1 gates; `draftFV.js:50-51` −3 / +5;
`g5FV.js:231-245`; `futureValue.js:536-548` FV_ANCHORS (cumulative discounted WAR, different
units); ★`devSignals.js:207-211` PEAK_BARS −1 / 0 / +1.5 (and the trained ML bars);
★`MockDraftPage.jsx:154`; ★`PlayerTable.jsx:178-183` min-value filter;
`RosterOptimizerPage.jsx:806` ✗ is a chart cell colour, not a model threshold.

**Pattern-matched readers**: ★`rosterOptimizer.js:1130 applyDurability` scales keys containing
`WAA`/`WAP` only — a `WAR` column would skip durability. `rosterOptimizer.js:135`,
`columns.js:336, 570` match `WAR`; `PlayerTable.jsx:42-50` and `seriesPlanner.js:200` hard-code
`WAA` names. Role choice in raw WAA: `orgBuilder.js:43-51, 100`.

**Standings**: `TeamStandingsPage.jsx:86-129` centres each total on the league mean; a uniform
role credit cancels only if every team fills the same slots (inferred).

## 3b. Decisions taken (2026-10-03) and what followed

- **D1 SSB replacement level — decided:** BLM's credits as a labelled proxy now; measure SSB's own.
  Done: SSB 2043 banked (`backtest/actuals/SSB/2043`, one `fetch_actuals.py` run). Budget identity,
  28 clubs × 162 G: **hitter 1.872 [1.57, 2.18], SP 2.630 [2.26, 3.00], RP 0.350 [0.20, 0.50]**
  (club bootstrap 95%), 33.66 WAR per club; the same code reproduces his BLM 2057 route-1 numbers
  exactly (1.912 / 2.643 / 0.298). Within error of BLM's, so the proxy holds; switching SSB to its
  own values is a sign-off item.
- **D2 where the block lives — decided:** `engine/calib/replacement.json` (outside the fingerprinted
  `calib/<LG>/` files). `engine/war.py` adds WAR columns beside WAA when a caller passes
  `live_replacement(app league)` (`ingest/refresh.py`, `ingest/export_league.py`); validators and the
  ML repricing never do. SSB rebuilt offline from its cached pull: 0 existing values changed in
  6,866 hitters / 7,125 pitchers; 41 hitter + 8 pitcher WAR columns; `Best Pos WAR` = `Best Pos` for
  all 475 SSB MLB hitters. BLM, TGS and RG get the columns at their next pull.
- **D3 swingman role — deferred** until all the data is in.
- **D5 thresholds — deferred** until there are real WAR values to look at (there now are, for SSB).
- **D4, D6** — open (explained to the user in plain terms).

## 4. Decisions needed before code (with the evidence gathered)

**D1 — SSB replacement level.** Options: BLM's measured values as a labelled proxy · measure
SSB's own · our FanGraphs constants (retired by the plan). `backtest/fetch_actuals.py --league SSB
--slug ssb --year 2043` banks a completed past season from public endpoints (about 5 requests:
/date, /lgdata, batting, pitching, fielding; a dry run without `--write` fetches but writes
nothing). Not run: it is a StatsPlus call. 2043 is SSB's only completed OOTP 27 season; 2044 adds
a second at season end. **Recommendation:** BLM proxy now, then bank 2043 and measure route 1
(budget identity) for SSB.

**D2 — where the block lives.** `currency.json` is fingerprinted (forces a full re-price) · a new
`engine/calib/<LG>/replacement.json`. **Recommendation:** the new file.

**D3 — swingman role.** All 296 BLM MLB dual-role arms carry `Starter = True` (that is what makes
them dual-role), so the flag cannot decide. Scored against real 2057 usage (169 arms with ≥ 5 MLB
games; SP if GS ≥ G/2; ratings are the current 2058-12 snapshot, so one season apart):

| Rule | Picks SP | Matches 2057 usage | Actual RP called SP | Actual SP called RP |
|---|---|---|---|---|
| WAA argmax (today's ML) | 118 / 296 | 129 / 169 = 76% | 24 | 16 |
| OOTP `POS` (SP vs RP/CL) | 177 / 296 | 127 / 169 = 75% | 32 | 10 |
| WAR argmax | 264 / 296 | 92 / 169 = 54% | 77 | 0 |

WAR argmax calls 77 of the 79 real relievers starters, because the SP credit is 2.19 wins larger
than the RP credit. **Recommendation:** decide the role in WAA (or by `POS`), then add that role's
credit — WAR prices the role a pitcher will fill, not the one that pays more.

**D4 — workload.** App BLM 0.930 / 0.990 (`leagueCalib.js:110-111`) vs fitted
`engine/calib/BLM/currency.json` 0.922 / 0.982 (refit 2026-10-01). **Recommendation:** read the
fitted file only.

**D5 — thresholds in WAR.** The generic ladder (≥5 / 3 / 1.5 / 0 / −1) on 875 BLM MLB players
(460 H, 118 SP, 297 RP; pitcher role by WAA argmax; catcher credit 5/6) puts 0.3 / 1.7 / 9.9 /
56.9 / 85.1% at or above each cut. A single WAR ladder keeping those shares cuts at **6.8 / 5.1 /
3.7 / 0.9 / 0.0**. Under it relievers fall: 47% of RPs are ≥ WAA 0 today, 7% would be ≥ 0.92 WAR.
A FanGraphs-style 6 / 4 / 2 / 0 / −1 puts 0.6 / 6.4 / 38.1 / 84.7 / 93.5% above the cuts.
**Recommendation:** the share-preserving cuts, rounded, shown to you before they ship. The other
WAA constants (§3) get the same treatment one by one.

**D6 — ML guard strictness** (implemented as warn). Refusing would stop the everyday pull after
every refit; warning records `{trained, current, match}` in `dev_ml.json`.

## 5. Done without decisions (on `phase1-war`)

- `leagueCalib` resolves by the manifest `basis` (SSB and RG were on TGS's constants);
  `tests/client/leagueCalib.test.mjs`.
- §2c guard: `calib_fingerprint` in both model manifests; `predict.calib_check` reads it (or the
  fingerprint inside older manifests' "DEV engine price tag" text); `score.py` warns and records.
- **Correction to the plan:** the `'WAR wtd'` refs (`columns.js:51, 838`, `PlayerDetail.jsx:412`)
  are not dead — `WAR wtd` is the pitcher column the engine will emit (plan §2b item 2). Kept.
- The optimizer's `_war` / `_spWAR` / `_rpWAR` have no readers but carry the org offset the plan
  keeps for cut/keep; they change when the optimizer switches to WAR, not before (no behaviour to
  gain, only merge churn).

## 6. Blocked on the ML models

Pitcher retrain on a WAR tuple, the hitter OOF-equality check, and the bar relabel (§2c) need the
trained models from his `.dev_cache` (not in the repo).
