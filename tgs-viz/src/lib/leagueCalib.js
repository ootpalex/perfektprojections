/**
 * leagueCalib.js — per-league FITTED calibration constants for the JS win/value
 * models (audit D2 / D6 / D9 / M5).
 *
 * EVERY number here is fitted or measured — no hand-chosen constants. Source of
 * truth: tgs-viz/engine/calib/<LEAGUE>/currency.json, produced by
 * tgs-viz/engine/currency_fit.py from the 260-season clone archives (TGS: 26
 * clones x 2016-2025; BLM: 7 clones x 2016-2026, partial 2027 dropped) and the
 * banked 2044 TGS actuals (backtest/actuals). Re-run that tool, then mirror any
 * changed values here (the app can't read engine/calib at runtime).
 *
 * Per-league fields:
 *  rpw            (D9) runs-per-win. Archive team-season regression of
 *                 (W - G/2) on run diff; the two OLS directions bracket truth
 *                 (TGS 10.83/10.48, BLM 10.40/9.69); shipped = geometric mean
 *                 ("mid-range spec"). The SAME value overrides Data Points H30
 *                 in the python engine, so WAA columns and these win models
 *                 price a win identically. (Sheet tangent values were
 *                 TGS 10.08 / BLM 9.94 — audit hypothesized BLM ~10.5; the fit
 *                 says 10.04, i.e. BLM's tangent was nearly right.)
 *  luckSD         (D9) the sim's own single-season win SD for FIXED talent:
 *                 across-year variance of each archive team's clone-mean wins,
 *                 scaled by the clone count. The Monte Carlo must not be
 *                 narrower than this.
 *  spWorkload     (D9) innings the sim actually hands a team's top-5 starters
 *                 vs the model's 5 x 800 BF (TGS 875/929 IP, BLM 870/943).
 *  rpWorkload     (D9) same for the top-8 relievers vs 8 x 300 BF
 *                 (TGS 533/557, BLM 556/566). The audit hypothesized ~0.90 on
 *                 the pen only; the measurement puts the pen near full (0.96/
 *                 0.99) and the ROTATION at ~0.93-0.94 — both are applied.
 *  rpEdgeSlope    (D6) calibration slope of ACTUAL RP RA/9 on the CURRENT
 *                 engine's projected RP RA/9 (2044 TGS season, snapshot join,
 *                 n=313, IP-weighted, r=0.46; robust 1.19-1.26 across specs).
 *                 The audit's backtest on the OLD engine hypothesized ~0.82
 *                 (shrink); after the D1 S-curve + D2 exponent rebuild the
 *                 SAME regression measures 1.249 — the old two-segment curves
 *                 under-spread RP talent so badly (old-engine slope on this
 *                 join: 1.83) that the fitted correction flipped from "shrink
 *                 edges 18%" to "expand edges 25%". Fitted on TGS, applied to
 *                 both leagues. BLM banked its first season (2057) on
 *                 2026-08-07 and this is now REFITTABLE for BLM — pending, via
 *                 currency_fit.py --rp-backtest; only replacementMarket was
 *                 re-measured from that bank so far.
 *  rpTalentSD     (D6) per-RP residual RA/9 spread around that calibration
 *                 line with the sim's own sampling noise removed (runs-allowed
 *                 as a count process: total resid 1.234, sampling floor 0.802,
 *                 talent residual 0.938). Widens the Monte Carlo's RA side.
 *  replacementMarket / replacementOrg — TWO measured replacement levels
 *                 (2026-08-07 re-measurement + market audit). They answer
 *                 different questions and must not be conflated:
 *
 *                 ORG ("next man up"): what an org already holds — for each
 *                 org the 26-man boundary is bracketed by its worst ROSTERED
 *                 value (13th bat / 5th SP / 8th RP) and its best NON-rostered
 *                 value; replacement = the org-mean midpoint, sign-flipped
 *                 into a WAR offset (scripts/measure_replacement.mjs). This is
 *                 the right zero for INTERNAL cut/keep decisions — the
 *                 rosterOptimizer's _war — because the alternative to keeping
 *                 a player is your own farm, not the open market.
 *
 *                 MARKET ("freely available"): what talent obtainable for
 *                 nothing on the open market actually produces — measured
 *                 from the FA/waiver pool, not org depth. Org depth is NOT
 *                 freely available to other teams (you can't sign another
 *                 org's 14th bat), so ORG overstates the true market floor.
 *                 This is the right zero for ANY $-layer or cross-role $/FV
 *                 comparison: salaries clear against what a team could sign
 *                 for free, so marketValue.js (getPlayerWAR, the FA fits,
 *                 offers) prices in MARKET WAR. Using ORG there compressed
 *                 hitter WAR and left a phantom $4-5M "floor" in the hitter
 *                 fit that was really unpriced replacement wins.
 *
 *                 WAR = WAA + offset(role) in BOTH currencies — pick the
 *                 offset set for the question being asked.
 */

export const LEAGUE_CALIB = {
  TGS: {
    rpw: 10.651,
    luckSD: 6.98,
    spWorkload: 0.942,
    rpWorkload: 0.957,
    rpEdgeSlope: 1.238,         // refit 2026-08-05 with the elite-K-knot engine
    rpTalentSD: 0.937,          // RA/9 units, per RP season
    rpModelIP: 69.68,           // H34-equivalent innings behind one RP slot
    // ORG ("next man up") — measured 2026-08-05 (re-measured post D3/D4/D8 +
    // elite-K rebuild): worst-rostered / next-man-up bracket the boundary at
    // hitter -1.543/-0.331, SP -0.256/-0.972, RP -0.162/-0.185; shipped =
    // midpoints. (Audit M5 hypothesis 0.8/0.4/0.05.) WHY: internal cut/keep —
    // the marginal roster spot competes with the org's own depth.
    replacementOrg: { hitter: 0.94, sp: 0.61, rp: 0.17 },
    // MARKET ("freely available") — re-measured 2026-08-07 from what
    // no-cost-acquirable talent actually produces (FA/waiver pool), per the
    // market audit. WHY: the $ layer — salaries clear against what a team
    // could sign for free, which is worse than org depth (other orgs' depth
    // isn't signable), so the market zero sits lower / the offsets higher.
    // SP/RP re-measured 2026-08-05 from the banked 2044 season via a budget
    // identity that cannot be argued with: TGS clubs actually produced 32.5 WAR
    // each (OOTP's own war column, 1040.6 league-wide), while the old offsets
    // (10x1.65 + 5x0.70 + 8x0.17) summed to 21.6 — implying a replacement team
    // wins 59 games when the sim measures 50 (.308, matching real MLB's ~.296).
    // Four independent routes put SP at 2.10-2.88 (budget identity 2.63,
    // delivered-WAR regression 2.65); 2.5 shipped, re-measure at each season bank.
    // Hitter 1.65 validated to within 1% — unchanged.
    replacementMarket: { hitter: 1.65, sp: 2.5, rp: 0.45 },
  },
  BLM: {
    rpw: 10.036,
    luckSD: 6.37,
    spWorkload: 0.922,          // currency.json refit 2026-10-01 (was 0.930)
    rpWorkload: 0.982,          // same (was 0.990); tests/client/leagueCalibSync.test.mjs keeps these equal
    rpEdgeSlope: 1.238,         // still TGS-fitted; BLM 2057 is banked, refit pending — see header
    rpTalentSD: 0.937,          // still TGS-fitted — same note
    rpModelIP: 70.13,
    // ORG ("next man up") — measured 2026-08-05 (re-measured post D3/D4/D8
    // rebuild): worst-rostered / next-man-up hitter -1.226/-0.046,
    // SP +0.040/-0.598, RP +0.013/-0.026; shipped = midpoints. WHY: internal
    // cut/keep — see TGS block.
    replacementOrg: { hitter: 0.64, sp: 0.28, rp: 0.01 },
    // MARKET — MEASURED 2026-08-07 from BLM's own first banked season (2057,
    // backtest/actuals/BLM/2057, season_complete: every club exactly 162 W+L,
    // league W==L==2430). This replaces the previous placeholders, which were
    // the ORG values for SP/RP (blocked-on-data) and a wide market-implied
    // 1.84 +/- 0.52 for the bat. Same routes as the TGS re-measurement:
    //   1. BUDGET IDENTITY (OOTP's own 'war' column, split_id 1 / lid 144 /
    //      level 1, stint-deduped): BLM clubs actually produced 33.35 WAR each
    //      (1000.6 league-wide; bat 19.15 / SP 11.70 / RP 2.50), so a
    //      replacement club wins 47.7 of 162 (.294) — and the direct
    //      teamWins-on-teamWAR regression independently puts the WAR=0 club at
    //      49.8 (.308, r2 .924). Both bracket real MLB's ~.296. Dividing each
    //      role's WAR by its slots/club on the engine's own full-season bases
    //      (10.01 bats at 600 PA, 4.43 SP at 800 BF, 8.41 RP at 300 BF) gives
    //      hitter 1.912 / SP 2.643 / RP 0.298. The old offsets summed to just
    //      19.75 WAR/club, implying a replacement club at 61.3 wins (.378) —
    //      the same 13.6-WAR/club hole the TGS audit found.
    //   2. DELIVERED-WAR REGRESSION (delivered OOTP war per full-season base
    //      on sheet WAA): hitter 2.059 [1.837, 2.278] n=204, SP 2.362
    //      [2.138, 2.579] n=117, RP 0.313 [0.216, 0.409] n=194 (bootstrap
    //      95% CI). BLM's live sheet is a 2058 vintage against a 2057 season,
    //      so this route carries a one-year aging gap; controlling for age
    //      moves the intercepts by <0.03 and an age-26-30 window by <0.17, so
    //      the gap is not what separates it from route 1.
    //   3. MARKET PIN (hitter only): the offset at which a 0-market-WAR bat
    //      prices at the league minimum = 1.815 [1.216, 2.466], n=30 FA
    //      signings. Kept because the same code recovers TGS's known 1.65 to
    //      +0.04. The role-line-agreement route was DROPPED, not averaged in:
    //      on TGS it misses the known SP 2.50 by -0.50 (and BLM's flat, RP-
    //      dominated FA pitcher sample makes it worse), so it is not evidence.
    // Shipped = the MEDIAN of the surviving routes per role. Scale check
    // (full-workload players, mean delivered vs mean sheet WAR): BLM's sheet
    // ran 2.10 low on SP, 0.32 low on RP, 0.14 low on bats — the TGS run
    // measured ~1.8 low on SP, i.e. the same defect, slightly larger here.
    // GATE: roster-sum 32.80 WAR/club vs 33.35 measured (gap -0.55) ->
    // replacement club .298 vs .294 measured; BLM's FA pitcher floor collapses
    // $2.20M -> $1.15M (3.15x -> 1.64x its $0.70M minimum), matching TGS's
    // $4.37M -> $1.53M (2.04x). Re-measure at each BLM season bank.
    replacementMarket: { hitter: 1.91, sp: 2.5, rp: 0.31 },
  },
};

// A league without its own block (SSB, RG, any wizard league) is priced by the engine
// on its manifest "basis" (TGS or BLM); the app must use the same calibration, or its
// $/FV/optimizer numbers disagree with the engine's WAA. useLeagues registers the
// bases when leagues.json loads.
const BASIS_OF = {};
export function setLeagueBases(leagues) {
  for (const k of Object.keys(BASIS_OF)) delete BASIS_OF[k];
  for (const lg of leagues || []) {
    if (lg && lg.id && lg.basis && LEAGUE_CALIB[lg.basis]) BASIS_OF[lg.id] = lg.basis;
  }
}

// Fallback for unknown league ids with no basis: TGS's fitted values (the primary league).
export function leagueCalib(league) {
  return LEAGUE_CALIB[league] || LEAGUE_CALIB[BASIS_OF[league]] || LEAGUE_CALIB.TGS;
}

/**
 * MARKET replacement offsets — WAR = WAA + offset(role) in the open-market
 * currency (see header). This is the offset every $/FV cross-role consumer
 * uses (marketValue, futureValue, draftFV, the pitcher-percentile metric):
 * dollars and FV rank players against what the market supplies for free.
 * Measured (see header); missing values fall back to 0 (WAR === WAA).
 */
export function replacementOffset(league, role) {
  const r = leagueCalib(league).replacementMarket || {};
  const v = r[role];
  return Number.isFinite(v) ? v : 0;
}

/**
 * ORG replacement offsets — WAR = WAA + offset(role) in the next-man-up
 * currency. ONLY for internal roster decisions (rosterOptimizer _war):
 * when deciding whom to cut/keep, the alternative is your own depth, not
 * the market. Do NOT price dollars in this currency.
 */
export function replacementOrgOffset(league, role) {
  const r = leagueCalib(league).replacementOrg || {};
  const v = r[role];
  return Number.isFinite(v) ? v : 0;
}
