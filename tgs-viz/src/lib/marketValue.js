/**
 * Market Value Calculator — FA-market-fitted $ layer.
 *
 * METHODOLOGY (v3, 2026-08-07). v1 divided TOTAL payroll by wins above
 * AVERAGE, pricing a win ~3x the real market. v2 fitted the actual FA market.
 * v3 fixes four measurement defects in v2's fit; every constant below is
 * measured from the league's own data at load time.
 *
 * 1. SAMPLE — fresh free-agent signings only: MLB players in year 1 of their
 *    contract (ContractYr === 1) whose service AT SIGNING was >= 6 service
 *    YEARS, tested in DAYS:
 *        serviceDaysAtSigning = MLBSvcDays - MLBSvcDaysTY  >=  6 * 172
 *    (the deal started this season, so this season's accrual came after the
 *    signature). v2 tested the INTEGER MLBSvcYrs, which is up to a year loose
 *    because that field is service NOW: a player who signed at 5.2 years and
 *    then played a full season reads as 6, so pre-free-agency EXTENSIONS
 *    entered the sample. They are 63% of the old TGS sample and 15% of BLM's,
 *    and they price ~$1.8M/yr BELOW the line at matched WAR in both leagues
 *    (measured), dragging the slope down and the floor up.
 *
 *    A service YEAR is 172 DAYS — MEASURED, not assumed. Route A (identity):
 *    mlb_service_years === floor(mlb_service_days / L) holds for L = 172 and
 *    for no other L in 120..210, over every player rostered in the MLB world
 *    (8,578 TGS / 13,876 BLM; the only violators anywhere are ex-NPB/KBO free
 *    agents in the TGS pool, who accrued service on a foreign league's shorter
 *    clock). Route B (economics, independent): with service measured AT
 *    SIGNING the salary ladder's arbitration step lands exactly between the
 *    2.000-3.000 and 3.000-4.000 service buckets in both leagues (at-minimum
 *    share TGS 55% -> 4%, BLM 80% -> 3%), and BLM's free-agency step (the
 *    onset of multi-year deals) peaks at 1012 days vs 6*172 = 1032.
 *    See ingest/statsplus.py for the field semantics.
 *
 * 2. CURRENCY — WAR = WAA + the MEASURED per-league **MARKET** replacement
 *    offsets from leagueCalib.js (replacementMarket: what freely-available
 *    talent produces). Salary clears against what a team could sign for FREE —
 *    the open-market floor — not against an org's own depth (replacementOrg,
 *    which only the rosterOptimizer's internal cut/keep uses).
 *
 * 3. RESPONSE = AAV, not year-1 price: sum(SalarySchedule)/years. Year 1 of a
 *    backloaded deal is not what the market paid. (Measured effect is small —
 *    schedules are near-flat in BOTH leagues, mean |AAV-Price|/Price 2.8% TGS
 *    / 1.5% BLM — but AAV is the correct variable and multi-year deals are
 *    ~half the sample.)
 *
 * 4. FLOOR — fitted with the intercept PINNED at the league minimum salary,
 *    which is itself MEASURED per league (measureLeagueMinimum: the modal
 *    salary among MLB players on a <=1-year deal who were pre-arb at signing —
 *    OOTP renews exactly those at the minimum; the mode carries 89% of that
 *    pool in TGS, 93% in BLM). Justification is empirical, not assumed: with
 *    the offsets fixed and the extensions removed, the FREE intercept is
 *    statistically indistinguishable from the measured minimum in every one of
 *    the six league x cell fits (t = -0.81/-0.18/-0.97 TGS,
 *    -0.60/+0.11/+0.25 BLM), and pinning tightens the slope CI by 45-53%.
 *    The pin is GATED at load by the same 1-SE rule as everything else: it
 *    ships unless the free line predicts better out of sample by more than one
 *    CV standard error. Measured: pinned wins outright in 5 of 6 cells; in the
 *    TGS pooled cell it is 0.63 SE worse, inside the tolerance, so it is kept.
 *    `floorMode` records which shipped.
 *
 * 5. SHAPE — a curvature term IS fitted (quadratic through the same floor) but
 *    it only ships if ALL FOUR gates hold: (a) monotone increasing over
 *    [0, top observed WAR]; (b) beats the line OUT OF SAMPLE by more than one
 *    CV standard error (the standard 1-SE rule, parsimony to the line);
 *    (c) its own deterministic bootstrap 95% CI excludes zero; (d) STABILITY —
 *    the verdict must survive dropping any single signing.
 *
 *    Measured on the current data: the curvature is REAL but NOT ESTABLISHED,
 *    so BOTH leagues ship straight lines and the audit's convexity finding is
 *    recorded as blocked on sample size, not implemented.
 *      TGS pooled  curv +$1.29M/WAR^2, bootstrap CI [+0.32, +2.14] (excludes
 *                  zero), OOS -4.8% vs the line at paired t=-1.01 — i.e. it
 *                  passed (a),(b),(c) by a hair and then FAILED (d): the very
 *                  first leave-one-out reversed it. Over the full jackknife the
 *                  curve held in only 13 of 55 drops.
 *      BLM pooled  curv +$0.72M/WAR^2, CI [+0.09, +1.31] (also excludes zero),
 *                  OOS -2.0% at t=-0.85 — fails (b). Its LINE is equally
 *                  fragile: it held in only 19 of 66 drops.
 *      role cells  all four rejected (n=23-43; CIs include zero; BLM's pitcher
 *                  quadratic is not even monotone).
 *    Read that as: both leagues' pooled samples show the SAME positive
 *    curvature with a CI excluding zero, which is real evidence that the audit
 *    was right about the shape — but at n=55/66 with a $6-9M residual SD the
 *    predictive test cannot tell a line from a curve, and a single contract
 *    flips it either way. Since adopting the curve would re-price a 4-WAR
 *    player by +$9.18M/yr and a 1-WAR player by -$1.77M/yr (almost exactly the
 *    audit's $8.8M and $1.7M), that is far too much movement to hang on one
 *    signing. Bank another offseason and re-read.
 *
 *    CAVEAT ON THE GATES THEMSELVES (adversarial verify pass, 2026-08-07) —
 *    "the gate turns the curve on by itself when the sample can carry it" is
 *    NOT true as implemented, and the two shape verdicts are less decisive
 *    than the numbers above read:
 *      (b) is SEED-DEPENDENT. Re-running the same paired CV over 200
 *          independent fold assignments: TGS t = -0.967 +/- 0.086, firing in
 *          37% of seeds; BLM t = -1.080 +/- 0.113, firing in 76%. The shipped
 *          CV_SEED draws -1.01 for TGS (fires) and -0.85 for BLM (does not) —
 *          BLM's rejection is roughly a bottom-quartile draw, not a finding.
 *          The gate is measuring CV noise as much as it is measuring the data.
 *      (d) is effectively UNPASSABLE, and gets stricter as the sample grows.
 *          It requires all n single-drop re-runs to independently clear the
 *          same noisy (b), so P(pass) ~ p^n: measured per-drop p = 0.27 (TGS,
 *          9e-32 over 55 drops) and 0.91 (BLM, 0.002 over 66). Banking more
 *          offseasons RAISES n and therefore LOWERS the chance the gate ever
 *          fires. It is a conservative failsafe, not a test that can turn on.
 *      What the data actually says, gates aside: TGS's curve IS fragile —
 *          dropping the top 2 signings by WAR puts its bootstrap CI back
 *          across zero, and dropping the top 5 collapses curv +1.29 -> +0.05.
 *          BLM's is sturdier under leave-one-out (60 of 66 drops hold) but
 *          equally dependent on its top handful (top-1 drop already recrosses
 *          zero). Both leagues' curvature rests on 2-5 contracts.
 *      Shipping the LINE remains the right call — a curve re-prices a 4-WAR
 *          player by ~+$9M/yr on that evidence — but if the shape is ever
 *          revisited, REPLACE gates (b)/(d) (e.g. average the paired t over
 *          many seeds; make stability a fraction-of-drops threshold rather
 *          than unanimity) rather than reading the current verdicts as
 *          measurements.
 *
 * 6. PER-ROLE vs POOLED — decided OUT OF SAMPLE per role, not assumed. v2 split
 *    hitter/pitcher on the theory that the two FLOORS meant different things;
 *    with the floor pinned that rationale is gone, so the only question left is
 *    whether the SLOPES differ. Each role uses its own line only when that line
 *    predicts its own signings better than the pooled fit under repeated
 *    k-fold CV (1-SE rule, parsimony to one shared line). Measured:
 *      TGS POOLS. Its role lines are $6.67M/WAR (hitter) and $5.52M/WAR
 *      (pitcher) — 17% apart, slope-difference t = 1.36, and each is ~2% WORSE
 *      than the pooled line out of sample. That is the audit's predicted
 *      post-offset-fix result: once the extensions are out and the offsets are
 *      right, the two roles buy wins at the same price, so one line ships
 *      ($5.98M/WAR) and the roles agree by construction.
 *      BLM SPLITS, and this is a REAL disagreement, not a fixable one:
 *      hitter $6.52M/WAR vs pitcher $2.71M/WAR (t = 4.57, CIs [5.10,7.93] and
 *      [1.90,3.52] do not overlap), and each role's own line is ~15% better out
 *      of sample. BLM's FA pitcher market is genuinely flat: r2 0.16, 14 of 43
 *      signings are relievers, its starters span only 1.40-3.59 projected WAR
 *      (nobody signed a high-WAR SP that offseason), and three pitchers
 *      projected at 1.96-2.72 WAR signed for the $0.70M league minimum. This is
 *      a data limitation of BLM's single banked offseason, and it is the one
 *      gate in this work that does NOT pass — see the report.
 *
 * 7. NO EXTRAPOLATION — applies to the CURVE: a quadratic is never evaluated
 *    above the highest WAR the market has actually priced (`maxX`); queries
 *    above it are answered AT that tier, the same rule localFit already used.
 *    A straight LINE is left free to extrapolate as it always did — see
 *    cellPrice for why.
 *
 * 8. TWO ECONOMIES — the fitted line is kept for surplus/value display ("line
 *    value"), but actual prices depart from it at the top. FAIR OFFERS are
 *    TIER-LOCAL: a LOESS-style local linear regression (tricube kernel, span
 *    0.4 — standard LOESS conventions) over the actual signings of
 *    comparable-WAR players. The replaceable/scarcity boundary is WHERE THE
 *    LOCAL PRICE DEPARTS THE LINE BY > 1 FITTED RESIDUAL SD and stays there
 *    over at least MIN_TIER_XS distinct observed WAR values
 *    (computeScarcityBoundary — the run requirement is v3: without it the
 *    "boundary" degenerated to the single top signing, i.e. a tier of one).
 *
 *    v3.1 (adversarial verify pass, 2026-08-07): the local price is now also
 *    bounded in **y** by the actual signings inside its own window — see
 *    localFit. Before that bound BLM's hitter offer curve quoted $60.56M at
 *    3.0 WAR, above the largest contract in the league ($49.87M). Fitted
 *    coefficients are unaffected (verified byte-identical); only the offer
 *    path and the scarcity boundary read localFit.
 *
 *    KNOWN, NOT FIXED — the LOESS offer curve is NOT MONOTONE in WAR where
 *    the sample is thin. Measured on the shipped data (0.1-WAR grid):
 *      TGS pooled  monotone in practice (one $30K dip at 0.1 WAR, n=55).
 *      BLM hitter  20 decreasing steps: 1.5 WAR -> $13.4M, 2.0 -> $9.9M,
 *                  3.0 -> $49.9M, 3.5 -> $31.4M, 5.0 -> $30.2M (n=23).
 *      BLM pitcher 17 decreasing steps: 0.0 -> $4.1M, 1.5 -> $2.3M,
 *                  3.0 -> $6.2M, 3.5 -> $19.8M (n=43).
 *    So in BLM the "Fair AAV" column can offer a worse player more than a
 *    better one. The cause is a local LINE fitted across gaps in a 23/43-point
 *    sample, not a coding error, and the honest fixes (isotonic/PAV smoothing,
 *    or a monotonicity constraint on the local fit) are a methodology change
 *    that would move every offer in the app — deliberately NOT made during a
 *    verification pass. Re-read after BLM banks a second offseason; if the
 *    curve is still non-monotone at n~130, constrain it. TGS is unaffected.
 * 9. VALUATION — multi-year: for each remaining SalarySchedule year y,
 *      surplus_y = (priceAt(agedWAR_y) - salary_y) * 0.97^y
 *    with agedWAR from the row's measured path (futureValue fullPath, the
 *    internal WAR track: growth to 27, then the measured DEV decline) when
 *    the DEV curve is loaded, else futureValue's getAgingFactor schedule.
 *    Both are anchored so that agedWAR_0 = today's WAR (the same basis the
 *    fit regressed on). 0.97 is futureValue's DISCOUNT_RATE (3%/yr time
 *    value).
 *    The FAIR-OFFER horizon is the player's OWN remaining control
 *    (serviceTime.controlWindow: service days vs the signed schedule), not the
 *    flat six years this file used to assume for everybody.
 *
 * WHAT REMAINS HEURISTIC OR CONVENTION (clearly labeled, not fitted):
 * - The fallback aging schedule (futureValue FV_DEFAULTS, INTERIM per the
 *   2026-08-05 directive). It runs only when no measured curve is loaded.
 * - Band width "1 SD" and the LOESS kernel/span (tricube, 0.4) are standard
 *   conventions; the dispersions themselves are fitted from real signings.
 * - CV protocol constants (10 folds, 20 repeats, "beat by 1 paired SE"): the
 *   standard one-standard-error model-selection rule. The comparisons
 *   themselves are data. The stability gate ("no single observation may
 *   reverse the verdict") is likewise a stated robustness convention, not a
 *   tuned threshold.
 * - Bootstrap B = 1000, seeded. Deterministic on purpose: the same data must
 *   always ship the same line.
 * - MIN_TIER_XS = 3: a scarcity "tier" has to contain more than one or two
 *   signings. A convention, but a necessary one — without it the boundary
 *   degenerated to the single top signing. On the current data no run of 3
 *   survives in either league, so the boundary is null and every player is
 *   labelled "replaceable"; the tier-local premium is still paid through the
 *   LOESS offer path, which is where it belongs.
 * - Per-role minimum sample n >= 10 before a role line is even considered
 *   (small-sample guard).
 * - Prospect development risk: the measured path (the DEV curve, with the ML
 *   model or the DEV cell gain) uses no risk factor. Its growth target is
 *   already the typical outcome for players like him, washouts counted. Only
 *   the fallback model (no DEV curve) applies futureValue's risk factor
 *   (0.80-0.95, labeled heuristic there).
 * - Market value is floored at $0/yr (you can release a negative-WAR player
 *   and pay a replacement nothing — value can't go below the walk-away point).
 *
 * KNOWN LIMITS (data, not code):
 * - Sample size. The honest filter leaves n=55 TGS / n=66 BLM fresh FA
 *   signings; per-role n is 23-43. Slope CIs are wide and every offseason's
 *   bank should re-tighten them.
 * - Vintage. The fit regresses THIS season's projected WAR on a price set in
 *   the previous offseason. TGS's snapshot is a full season after signing
 *   (in-game 2044-10-20, deals dated 2044); BLM's is ~2 months after
 *   (2058-05-27, deals dated 2058).
 * - Mid-season signings. serviceDaysAtSigning credits the whole current-season
 *   accrual to after the signature, so a player signed mid-season is credited
 *   up to `MLBSvcDaysTY` days too little. That biases toward EXCLUDING, never
 *   toward admitting an extension.
 */

import { getAgingFactor, FV_DEFAULTS, measuredPath } from './futureValue.js';
import { curveShape } from './ageCurve.js';
import { replacementOffset } from './leagueCalib.js';
import {
  SVC_YEAR_DAYS, FA_SERVICE_YEARS, ARB_SERVICE_YEARS, svcYearDays, controlWindow,
} from './serviceTime.js';

// ============================================================
// WAR BASIS (audit M5 currency: WAA + measured replacement offsets)
// ============================================================

function toNum(v) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

/** 'hitter' | 'pitcher' by which WAA columns the row carries. */
export function getPlayerRole(player) {
  if (player['Max WAA wtd'] !== undefined || player['Max WAA vR'] !== undefined) return 'hitter';
  if (player['WAA wtd'] !== undefined || player['WAA wtd RP'] !== undefined) return 'pitcher';
  return 'hitter';
}

/**
 * Best current WAR for a player: best role WAA + that role's measured
 * MARKET replacement offset (leagueCalib replacementMarket, keyed by
 * _appLeague) — the open-market currency salaries clear in. Identical to the
 * currency futureValue's getPlayerWAAValues uses for currentWAA.
 */
// ============================================================
// HEALTH RISK DISCOUNT ($ layer only)
// ============================================================

// What a durability flag is worth in MONEY. A draft policy, not an estimate: the user
// will pay 40 cents on the dollar for a Wrecked player and 75 for a Fragile one, because
// the projection prices the seasons he is on the field for and says nothing about how
// often he is not. Injury proneness is real and externally tracked; these set the premium
// demanded for carrying that risk. Deliberately applied ONLY to dollars — WAR, WAA and
// every rating-driven projection stay untouched, so the flag never quietly edits talent.
const HEALTH_VALUE_FACTOR = { 'Wrecked': 0.40, 'Fragile': 0.75 };

export function healthValueFactor(player) {
  return HEALTH_VALUE_FACTOR[player && player.Prone] ?? 1.0;
}

/**
 * Scale every dollar VALUE in a calculatePlayerValue result by the player's health
 * factor. Salary is never scaled — an obligation is an obligation — so each surplus is
 * re-derived rather than scaled: surplus = f*value - salary = surplus - (1-f)*value.
 */
function applyHealthDiscount(out, player) {
  const f = healthValueFactor(player);
  out.healthFactor = f;
  out.proneValue = (player && player.Prone) || null;
  if (f === 1) return out;
  const s = (v) => (Number.isFinite(v) ? Math.round(v * f) : v);
  const drop = (v) => (Number.isFinite(v) ? Math.round((1 - f) * v) : 0);

  // surpluses first — they need the UNDISCOUNTED value they were derived from
  out.surplus = Number.isFinite(out.surplus) ? out.surplus - drop(out.annualValue) : out.surplus;
  out.marketSurplus = Number.isFinite(out.marketSurplus)
    ? out.marketSurplus - drop(out.marketPrice) : out.marketSurplus;

  for (const k of ['annualValue', 'marketPrice', 'localSD',
                   'offerFloor', 'offerMid', 'offerCeiling',
                   'futureAnnualValue', 'futureOfferFloor', 'futureOfferMid',
                   'futureOfferCeiling', 'totalValue', 'adjustedValue']) {
    out[k] = s(out[k]);
  }
  if (Array.isArray(out.yearlyValues)) {
    out.yearlyValues = out.yearlyValues.map(y => ({ ...y, yearValue: s(y.yearValue) }));
  }
  if (Array.isArray(out.offerByLength)) {
    out.offerByLength = out.offerByLength.map(o => ({
      ...o, aav: s(o.aav), total: s(o.total), low: s(o.low), high: s(o.high),
    }));
  }
  if (out.contract) {
    const c = out.contract;
    out.contract = {
      ...c,
      surplus: Number.isFinite(c.surplus) ? c.surplus - drop(c.totalValue) : c.surplus,
      totalValue: s(c.totalValue),   // totalSalary is NOT scaled
      years: Array.isArray(c.years) ? c.years.map(y => ({
        ...y,
        surplus: Number.isFinite(y.surplus) ? y.surplus - drop(y.value) : y.surplus,
        discSurplus: Number.isFinite(y.discSurplus) && Number.isFinite(y.value)
          ? y.discSurplus - drop(y.value) : y.discSurplus,
        value: s(y.value),
      })) : c.years,
    };
  }
  return out;
}

export function getPlayerWAR(player) {
  const lg = player._appLeague;
  let best = null;
  const consider = (col, off) => {
    const v = toNum(player[col]);
    if (v !== null && (best === null || v + off > best)) best = v + off;
  };
  if (getPlayerRole(player) === 'hitter') {
    const hOff = replacementOffset(lg, 'hitter');
    consider('Max WAA wtd', hOff);
    consider('Max WAA vR', hOff);
  } else {
    consider('WAA wtd', replacementOffset(lg, 'sp'));
    consider('WAA wtd RP', replacementOffset(lg, 'rp'));
  }
  return best;
}

/** Legacy raw best-WAA (no offsets) — kept for display columns. */
export function getBestWAA(player) {
  const cols = ['Max WAA wtd', 'WAA wtd', 'WAA wtd RP'];
  let best = -Infinity;
  for (const col of cols) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val > best) best = val;
  }
  return best === -Infinity ? 0 : best;
}

export function isBetterAsRP(player) {
  const sp = parseFloat(player['WAA wtd']) || 0;
  const rp = parseFloat(player['WAA wtd RP']) || 0;
  return rp > sp;
}

// ============================================================
// SERVICE TIME + CONTRACT BASIS (v3)
// ============================================================

// The service constants and the day-length override now live in serviceTime.js
// (the remaining-control module needs them and must not import this file back).
// Re-exported here because this is where they have always been imported from.
export { SVC_YEAR_DAYS, FA_SERVICE_YEARS, ARB_SERVICE_YEARS };

/**
 * MLB service DAYS the player had when he signed his CURRENT deal, for a deal
 * that started this season (ContractYr === 1): everything he accrued this
 * season came after the signature.
 * Returns null when the day-resolution fields are absent (pre-v3 JSON).
 */
export function serviceDaysAtSigning(p) {
  const d = toNum(p.MLBSvcDays);
  if (d === null) return null;
  return d - (toNum(p.MLBSvcDaysTY) ?? 0);
}

/** Average annual value of the remaining deal — the price the market set. */
export function contractAAV(p) {
  const sched = Array.isArray(p.SalarySchedule)
    ? p.SalarySchedule.filter(Number.isFinite) : [];
  if (sched.length) {
    const tot = sched.reduce((s, v) => s + v, 0);
    if (tot > 0) return tot / sched.length;
  }
  const price = toNum(p.Price);
  return price !== null && price > 0 ? price : null;
}

/**
 * The league MINIMUM salary, MEASURED from the league's own data: the modal
 * salary among MLB players on a <=1-year deal who were PRE-ARB at signing.
 * OOTP renews exactly that group at the minimum, so the mode IS the minimum.
 * Returns { value, n, pool, share, isFloor } — `share` is the mode's share of
 * that pool and `isFloor` records the consistency check that no one in the
 * pool is paid LESS (a minimum that isn't a floor isn't a minimum).
 */
export function measureLeagueMinimum(players, opts) {
  const L = svcYearDays(opts);
  const counts = new Map();
  let pool = 0, lowest = Infinity;
  const anyCounts = new Map();
  for (const p of players) {
    if (p.Lev !== 'MLB') continue;
    const price = toNum(p.Price);
    if (price === null || price <= 0) continue;
    anyCounts.set(price, (anyCounts.get(price) || 0) + 1);
    const yrs = toNum(p.ContractYrs);
    if (yrs !== null && yrs > 1) continue;
    const svcDays = serviceDaysAtSigning(p);
    const preArb = svcDays !== null
      ? svcDays < ARB_SERVICE_YEARS * L
      : (toNum(p.MLBSvcYrs) ?? 99) < ARB_SERVICE_YEARS;
    if (!preArb) continue;
    counts.set(price, (counts.get(price) || 0) + 1);
    pool += 1;
    if (price < lowest) lowest = price;
  }
  const src = counts.size ? counts : anyCounts;
  const usedPool = counts.size ? pool : Array.from(anyCounts.values()).reduce((a, b) => a + b, 0);
  if (!src.size) return null;
  let value = null, best = -1;
  for (const [k, v] of src) if (v > best || (v === best && k < value)) { best = v; value = k; }
  return {
    value, n: best, pool: usedPool,
    share: usedPool ? best / usedPool : 0,
    isFloor: counts.size ? value <= lowest : null,
    fallback: !counts.size,
  };
}

/**
 * True free-agent signing filter (v3): MLB, priced, deal started this season,
 * and >= FA_SERVICE_YEARS of service IN DAYS **at signing**. Falls back to the
 * loose integer-year test only when the day fields are missing from the JSON
 * (stale data) — fitFAMarket reports that as `serviceBasis: 'years (LEGACY)'`.
 */
function isFreshFASigning(p, basis, L) {
  if (p.Lev !== 'MLB') return false;
  if (toNum(p.ContractYr) !== 1) return false;
  const aav = contractAAV(p);
  if (aav === null || aav <= 0) return false;
  if (basis === 'days') {
    const d = serviceDaysAtSigning(p);
    return d !== null && d >= FA_SERVICE_YEARS * L;
  }
  const svc = toNum(p.MLBSvcYrs);
  return svc !== null && svc >= FA_SERVICE_YEARS;
}

// ============================================================
// FIT PRIMITIVES
// ============================================================

/** Plain OLS y = slope*x + intercept with slope SE and residual SD. */
function olsFit(points) {
  const n = points.length;
  if (n < 3) return null;
  let mx = 0, my = 0;
  for (const p of points) { mx += p.x; my += p.y; }
  mx /= n; my /= n;
  let sxx = 0, sxy = 0, syy = 0;
  for (const p of points) {
    sxx += (p.x - mx) * (p.x - mx);
    sxy += (p.x - mx) * (p.y - my);
    syy += (p.y - my) * (p.y - my);
  }
  if (sxx <= 0 || syy <= 0) return null;
  const slope = sxy / sxx;
  const floor = my - slope * mx;
  let ssr = 0;
  for (const p of points) {
    const e = p.y - (floor + slope * p.x);
    ssr += e * e;
  }
  // SE of the intercept — used to test the floor against the league minimum.
  const seFloor = Math.sqrt(ssr / (n - 2)) * Math.sqrt(1 / n + (mx * mx) / sxx);
  return {
    slope, floor, r2: 1 - ssr / syy, n,
    seSlope: Math.sqrt(ssr / (n - 2) / sxx),
    seFloor,
    residSD: Math.sqrt(ssr / (n - 2)),
  };
}

/** OLS with the intercept PINNED: (y - floor) = slope * x through the origin. */
function olsPinnedFit(points, floor) {
  const n = points.length;
  if (n < 3 || !Number.isFinite(floor)) return null;
  let sxx = 0, sxy = 0, my = 0;
  for (const p of points) { sxx += p.x * p.x; sxy += p.x * (p.y - floor); my += p.y; }
  if (sxx <= 0) return null;
  my /= n;
  const slope = sxy / sxx;
  let ssr = 0, syy = 0;
  for (const p of points) {
    const e = p.y - (floor + slope * p.x);
    ssr += e * e;
    syy += (p.y - my) * (p.y - my);
  }
  if (syy <= 0) return null;
  return {
    slope, floor, r2: 1 - ssr / syy, n,
    seSlope: Math.sqrt(ssr / (n - 1) / sxx),
    seFloor: 0,
    residSD: Math.sqrt(ssr / (n - 1)),
  };
}

/** (y - floor) = b*x + c*x^2 — the curvature candidate, same pinned floor. */
function quadPinnedFit(points, floor) {
  const n = points.length;
  if (n < 6 || !Number.isFinite(floor)) return null;
  let s11 = 0, s12 = 0, s22 = 0, t1 = 0, t2 = 0, my = 0;
  for (const p of points) {
    const x = p.x, d = p.y - floor;
    s11 += x * x; s12 += x * x * x; s22 += x * x * x * x;
    t1 += x * d; t2 += x * x * d; my += p.y;
  }
  my /= n;
  const det = s11 * s22 - s12 * s12;
  if (!(Math.abs(det) > 1e-9)) return null;
  const slope = (t1 * s22 - t2 * s12) / det;
  const curv = (s11 * t2 - s12 * t1) / det;
  let ssr = 0, syy = 0;
  for (const p of points) {
    const e = p.y - (floor + slope * p.x + curv * p.x * p.x);
    ssr += e * e;
    syy += (p.y - my) * (p.y - my);
  }
  if (syy <= 0) return null;
  return {
    slope, curv, floor, r2: 1 - ssr / syy, n,
    seSlope: Math.sqrt(ssr / Math.max(n - 2, 1) / Math.max(s11, 1e-9)),
    seFloor: 0,
    residSD: Math.sqrt(ssr / Math.max(n - 2, 1)),
  };
}

// --- deterministic cross-validation ------------------------------------
// Model selection must not depend on Math.random: the same data must always
// produce the same shipped line. mulberry32 with a fixed seed.
const CV_K = 10;        // folds
const CV_REPS = 20;     // repeats (convention)
const CV_SEED = 0x9E3779B9;

function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Repeated k-fold CV of several candidate models over the SAME folds, so the
 * per-fold errors are paired. `models` = [{ build(trainPts), predict(m, x) }].
 * Optionally scores on a different point set than it trains on (`scoreOn`),
 * which is how the pooled line is judged on one role's own signings.
 * Returns { rmse: number[], folds: number[][] } (folds = per-fold MSE).
 */
function cvCompare(points, models, scoreOn) {
  const score = scoreOn || points;
  const n = score.length;
  if (n < CV_K || n < 8) return null;
  const rnd = mulberry32(CV_SEED);
  const folds = models.map(() => []);
  for (let rep = 0; rep < CV_REPS; rep++) {
    const order = score.map((_, i) => i);
    for (let i = n - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1));
      const t = order[i]; order[i] = order[j]; order[j] = t;
    }
    for (let f = 0; f < CV_K; f++) {
      const held = new Set();
      for (let i = f; i < n; i += CV_K) held.add(score[order[i]]);
      if (!held.size) continue;
      const train = points.filter(p => !held.has(p));
      const test = Array.from(held);
      if (train.length < 6) continue;
      for (let mi = 0; mi < models.length; mi++) {
        const m = models[mi].build(train);
        if (!m) { folds[mi].push(NaN); continue; }
        let sse = 0;
        for (const p of test) {
          const e = p.y - models[mi].predict(m, p.x);
          sse += e * e;
        }
        folds[mi].push(sse / test.length);
      }
    }
  }
  const rmse = folds.map(a => {
    const v = a.filter(Number.isFinite);
    return v.length ? Math.sqrt(v.reduce((s, x) => s + x, 0) / v.length) : NaN;
  });
  return { rmse, folds };
}

/**
 * Paired comparison of two models' fold MSEs, in the form the standard
 * ONE-STANDARD-ERROR RULE needs (Breiman/Hastie): the SE is the fold-to-fold
 * SD divided by sqrt(K) — the K folds of a pass are the K quasi-independent
 * error estimates. Repeats only stabilise the mean; they do NOT buy degrees of
 * freedom (all repeats resample the same rows), so dividing by sqrt(reps)
 * would manufacture significance. t < -1 means A beats B by more than 1 SE.
 */
function pairedT(a, b) {
  const d = [];
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    if (Number.isFinite(a[i]) && Number.isFinite(b[i])) d.push(a[i] - b[i]);
  }
  if (d.length < 4) return null;
  const mean = d.reduce((s, x) => s + x, 0) / d.length;
  const sd = Math.sqrt(d.reduce((s, x) => s + (x - mean) ** 2, 0) / (d.length - 1));
  const se = sd / Math.sqrt(CV_K);
  return { mean, se, t: se > 0 ? mean / se : 0 };
}

/**
 * Deterministic percentile bootstrap CI of one fitted coefficient — the honest
 * error bar a coefficient has to clear before it is allowed to move prices.
 */
const BOOT_B = 1000;
const BOOT_SEED = 0x2545F491;

function bootstrapCI(points, build, key) {
  const n = points.length;
  if (n < 8) return null;
  const rnd = mulberry32(BOOT_SEED);
  const vals = [];
  for (let b = 0; b < BOOT_B; b++) {
    const rs = new Array(n);
    for (let i = 0; i < n; i++) rs[i] = points[Math.floor(rnd() * n)];
    const f = build(rs);
    if (f && Number.isFinite(f[key])) vals.push(f[key]);
  }
  if (vals.length < BOOT_B * 0.8) return null;
  vals.sort((x, y) => x - y);
  const lo = vals[Math.floor(0.025 * vals.length)];
  const hi = vals[Math.min(vals.length - 1, Math.floor(0.975 * vals.length))];
  return { lo, hi, excludesZero: lo > 0 || hi < 0 };
}

// ============================================================
// SHAPE SELECTION (floor pin + curvature), all gated out-of-sample
// ============================================================

/**
 * Evaluate a fitted cell at WAR w.
 *
 * NO EXTRAPOLATION applies to the CURVE only: a quadratic run past the last
 * observed signing accelerates into prices nobody has ever paid, so above
 * `maxX` a curve is evaluated AT maxX (the top observed tier — the same rule
 * localFit already uses for the prices you actually pay). A straight LINE is
 * left free to extrapolate exactly as it did before v3: clamping it too would
 * silently flat-line every player above the last FA signing, which is a much
 * larger behaviour change than the curvature work and is not what the line is
 * for (it is the "value" basis; offers already go through the clamped LOESS).
 * The lower guard keeps a convex curve on its increasing branch; the shape gate
 * puts that turning point below 0, so it only bites at deeply negative WAR,
 * where the $0 walk-away floor dominates anyway.
 */
function cellPrice(cell, w) {
  if (!cell) return 0;
  let x = w;
  if (cell.curv) {
    x = Math.min(x, cell.maxX);
    if (cell.curv > 0) x = Math.max(x, -cell.slope / (2 * cell.curv));
  }
  return Math.max(0, cell.floor + cell.slope * x + (cell.curv || 0) * x * x);
}

/**
 * Fit ONE fixed specification — no model selection, so it can be called inside
 * cross-validation without nesting a selection loop inside every fold.
 * spec = { floorMode: 'pinned'|'free', shape: 'line'|'quad' }.
 * `maxX` comes from the points the model was TRAINED on: a model may not
 * extrapolate past data it has not seen, in CV or in production.
 */
function fitSpec(points, minSalary, spec) {
  const base = spec.floorMode === 'pinned' && Number.isFinite(minSalary)
    ? olsPinnedFit(points, minSalary)
    : olsFit(points);
  if (!base) return null;
  const maxX = points.reduce((m, p) => Math.max(m, p.x), -Infinity);
  const minX = points.reduce((m, p) => Math.min(m, p.x), Infinity);
  if (spec.shape === 'quad') {
    const q = quadPinnedFit(points, base.floor);
    if (q) return { ...q, curv: q.curv, maxX, minX, shape: 'quad', floorMode: spec.floorMode };
    return null;
  }
  return { ...base, curv: 0, maxX, minX, shape: 'line', floorMode: spec.floorMode };
}

/**
 * Fit one cell (pooled / hitter / pitcher): choose the floor (pinned vs free)
 * and the shape (line vs curve). Both choices are made by the standard
 * ONE-STANDARD-ERROR RULE on repeated k-fold CV — the simpler model wins ties —
 * and the curve additionally has to clear its own bootstrap CI and stay
 * monotone over the observed range.
 */
function fitCell(points, minSalary) {
  const free = fitSpec(points, minSalary, { floorMode: 'free', shape: 'line' });
  if (!free) return null;
  const { maxX, minX } = free;
  const pinned = Number.isFinite(minSalary)
    ? fitSpec(points, minSalary, { floorMode: 'pinned', shape: 'line' }) : null;

  // --- floor: pin unless the pin is WORSE out of sample by more than 1 SE.
  // (Parsimony favours the pin: it spends one fewer parameter on a quantity the
  // league already publishes, so it is the model to beat.)
  let floorMode = 'free', cvFloor = null;
  if (pinned) {
    const cv = cvCompare(points, [
      { build: P => fitSpec(P, minSalary, { floorMode: 'pinned', shape: 'line' }),
        predict: cellPrice },
      { build: P => fitSpec(P, minSalary, { floorMode: 'free', shape: 'line' }),
        predict: cellPrice },
    ]);
    const pt = cv ? pairedT(cv.folds[0], cv.folds[1]) : null;
    const pinWorse = pt ? pt.mean > pt.se : false;
    if (!pinWorse) floorMode = 'pinned';
    cvFloor = cv && pt
      ? { rmsePinned: cv.rmse[0], rmseFree: cv.rmse[1], t: pt.t, kept: !pinWorse }
      : { rmsePinned: null, rmseFree: null, t: null, kept: true };
    if (!cv || !pt) floorMode = 'pinned';   // too small to test: keep the pin
  }
  const base = floorMode === 'pinned' ? pinned : free;

  // --- shape: adopt the curve only if ALL THREE gates hold —
  //   (1) monotone increasing over [0, top observed WAR],
  //   (2) beats the line out of sample by more than 1 CV SE (1-SE rule),
  //   (3) the curvature's own bootstrap 95% CI excludes zero.
  const buildQuad = (P) => {
    const b = fitSpec(P, minSalary, { floorMode, shape: 'line' });
    if (!b) return null;
    const q = quadPinnedFit(P, b.floor);
    if (!q) return null;
    return {
      ...q, curv: q.curv, shape: 'quad',
      maxX: P.reduce((m, p) => Math.max(m, p.x), -Infinity),
    };
  };
  const lineSpec = { floorMode, shape: 'line' };
  const shapeGates = (pts) => {
    const q = buildQuad(pts);
    if (!q) return { ok: false, monotone: false, beatsOOS: false, pt: null };
    const mx = pts.reduce((m, p) => Math.max(m, p.x), -Infinity);
    const monotone = q.slope > 0 && (q.slope + 2 * q.curv * mx) > 0;
    const cv = cvCompare(pts, [
      { build: buildQuad, predict: cellPrice },
      { build: P => fitSpec(P, minSalary, lineSpec), predict: cellPrice },
    ]);
    const pt = cv ? pairedT(cv.folds[0], cv.folds[1]) : null;
    const beatsOOS = pt ? pt.mean < -pt.se : false;
    return { ok: monotone && beatsOOS, monotone, beatsOOS, pt, cv };
  };

  const quadFit = buildQuad(points);
  let shape = 'line', cvShape = null, curveCI = null, curveRejected = null;
  if (quadFit) {
    const g = shapeGates(points);
    curveCI = bootstrapCI(points, buildQuad, 'curv');
    const measurable = !!(curveCI && curveCI.excludesZero);

    // STABILITY: no single signing may decide the shape. Re-run the gates with
    // each point dropped; if any drop reverses the verdict, the sample cannot
    // tell a line from a curve and the LINE (the simpler model) ships.
    // Measured on this data: TGS's curve survived only 24% of drops and BLM's
    // line only 29%, which is what forced this gate into existence — a $9M/yr
    // re-pricing of a 4-WAR player must not hinge on one contract.
    let looAgree = 0, looTested = 0, looRan = false;
    if (g.ok && measurable) {
      looRan = true;
      for (let i = 0; i < points.length; i++) {
        const sub = points.filter((_, j) => j !== i);
        looTested += 1;
        if (shapeGates(sub).ok) looAgree += 1;
        else break;   // one reversal is enough to fail the gate
      }
    }
    const stable = looRan && looAgree === points.length;
    const adopt = g.ok && measurable && stable;

    cvShape = g.cv && g.pt
      ? {
        rmseQuad: g.cv.rmse[0], rmseLine: g.cv.rmse[1], t: g.pt.t,
        monotone: g.monotone, measurable, stable,
        looAgree, looTested, looTotal: points.length, adopted: adopt,
      }
      : null;
    if (adopt) shape = 'quad';
    else {
      const why = [];
      if (!g.monotone) why.push('not monotone over the observed WAR range');
      if (!g.beatsOOS) {
        why.push(g.pt ? `no out-of-sample gain (paired t=${g.pt.t.toFixed(2)}, needs < -1)`
          : 'sample too small to cross-validate');
      }
      if (!measurable) {
        why.push(curveCI
          ? `curvature CI [${(curveCI.lo / 1e6).toFixed(2)}, ${(curveCI.hi / 1e6).toFixed(2)}]M/WAR^2 includes 0`
          : 'curvature CI not computable');
      }
      if (g.ok && measurable && !stable) {
        why.push('unstable — dropping a single signing reverses it '
          + `(the verdict held for ${looAgree} of the first ${looTested} drops tested, `
          + `then flipped; the gate stops at the first reversal)`);
      }
      curveRejected = why.join('; ');
    }
  }

  const chosen = shape === 'quad'
    ? { ...quadFit, curv: quadFit.curv, maxX, minX }
    : base;
  return {
    slope: chosen.slope,
    floor: chosen.floor,
    curv: shape === 'quad' ? quadFit.curv : 0,
    shape, floorMode,
    n: chosen.n, r2: chosen.r2, residSD: chosen.residSD,
    seSlope: chosen.seSlope, seFloor: chosen.seFloor,
    maxX, minX,
    free, pinned, quadCandidate: quadFit,
    // free-intercept vs the MEASURED minimum — the evidence for/against pinning
    floorVsMin: Number.isFinite(minSalary) && free.seFloor > 0
      ? (free.floor - minSalary) / free.seFloor : null,
    cvFloor, cvShape, curveCI, curveRejected,
    spec: { floorMode, shape },
  };
}

/**
 * Sample size backing a fit — the single number the banking script and the
 * live-vs-banked choice below both key off, so they can never disagree about
 * which of two fits is better supported.
 */
export function marketFitSupport(fit) {
  return fit && fit.pooled ? fit.pooled.n : 0;
}

/**
 * Fit the FA market from the loaded league rows. Re-runs on every data
 * refresh — nothing here is hardcoded to a league.
 *
 * opts.banked — a previously banked fit for THIS league (scripts/bank_market_fit.mjs
 * writes public/data/<LG>/market_fit.json). When free agency opens, OOTP resets
 * ContractYr across the whole league and the open-market sample collapses to a
 * handful of deals; the line refitted on those is noise, not a new measurement
 * of the price of a win. So when the bank rests on more signings than the live
 * sample does, the banked fit is returned unchanged. Nothing about the fitting
 * itself changes — this is only a choice between two already-computed fits.
 */
export function fitFAMarket(hitters, pitchers, opts) {
  const L = svcYearDays(opts);
  const all = [...(hitters || []), ...(pitchers || [])];
  // Day-resolution service is required for the honest filter; fall back loudly.
  const hasDays = all.some(p => p.Lev === 'MLB' && toNum(p.MLBSvcDays) !== null);
  const serviceBasis = hasDays ? 'days' : 'years (LEGACY — rebuild the JSON)';
  const minInfo = measureLeagueMinimum(all, opts);
  const minSalary = minInfo ? minInfo.value : null;

  const sample = [];
  let extensionsDropped = 0;
  for (const [players, role] of [[hitters, 'hitter'], [pitchers, 'pitcher']]) {
    for (const p of players || []) {
      if (p.Lev !== 'MLB' || toNum(p.ContractYr) !== 1) continue;
      const aav = contractAAV(p);
      if (aav === null || aav <= 0) continue;
      const war = getPlayerWAR(p);
      if (war === null) continue;
      if (!isFreshFASigning(p, hasDays ? 'days' : 'years', L)) {
        // count what the loose v2 filter WOULD have admitted, for the report
        if ((toNum(p.MLBSvcYrs) ?? -1) >= FA_SERVICE_YEARS) extensionsDropped += 1;
        continue;
      }
      const svcDays = serviceDaysAtSigning(p);
      sample.push({
        x: war, y: aav, role,
        name: p.Name, pos: p.POS, org: p.ORG, age: p.Age,
        price: toNum(p.Price), years: Array.isArray(p.SalarySchedule)
          ? p.SalarySchedule.filter(Number.isFinite).length : 1,
        svcAtSigning: svcDays === null ? null : svcDays / L,
      });
    }
  }

  const hitPts = sample.filter(s => s.role === 'hitter');
  const pitPts = sample.filter(s => s.role === 'pitcher');
  const pooled = fitCell(sample, minSalary);
  const hitter = fitCell(hitPts, minSalary);
  const pitcher = fitCell(pitPts, minSalary);

  // Welch t on the slope difference — displayed information.
  let slopeDiffT = null;
  if (hitter && pitcher) {
    const se = Math.sqrt(hitter.seSlope ** 2 + pitcher.seSlope ** 2);
    slopeDiffT = se > 0 ? Math.abs(pitcher.slope - hitter.slope) / se : 0;
  }

  // PER-ROLE vs POOLED, decided OUT OF SAMPLE per role: a role uses its own
  // line only when that line predicts ITS OWN signings better than the pooled
  // line does. (With the floor pinned, the v2 rationale — "the two floors are
  // different real quantities" — no longer applies; only the slopes are at
  // stake, and a split that doesn't pay for itself just adds variance.)
  // The specs are the ones already selected on the full data; CV refits only
  // their coefficients per fold (nesting the selection inside every fold would
  // make the comparison unstable and is not what ships).
  const useRoleLine = { hitter: false, pitcher: false };
  const roleCV = {};
  const roleUsable = (f) => !!(f && f.n >= 10 && f.slope > 0);
  for (const [role, cell, pts] of [['hitter', hitter, hitPts], ['pitcher', pitcher, pitPts]]) {
    if (!roleUsable(cell) || !pooled) continue;
    const cv = cvCompare(sample, [
      { build: P => fitSpec(P.filter(q => q.role === role), minSalary, cell.spec),
        predict: cellPrice },
      { build: P => fitSpec(P, minSalary, pooled.spec), predict: cellPrice },
    ], pts);
    const pt = cv ? pairedT(cv.folds[0], cv.folds[1]) : null;
    // 1-SE rule again, parsimony on the side of ONE shared line.
    const better = pt ? pt.mean < -pt.se : false;
    roleCV[role] = cv && pt
      ? { rmseRole: cv.rmse[0], rmsePooled: cv.rmse[1], t: pt.t, useRole: better }
      : null;
    useRoleLine[role] = better;
  }
  const perRole = useRoleLine.hitter || useRoleLine.pitcher;
  const ratioPH = hitter && pitcher && hitter.slope > 0 ? pitcher.slope / hitter.slope : null;

  const notes = [];
  notes.push(`service basis: ${serviceBasis}, ${L}-day service year`
    + (L === SVC_YEAR_DAYS ? ' (measured)' : ' (OVERRIDE — sensitivity run, not the shipped value)'));
  if (minInfo) {
    notes.push(`league minimum $${(minInfo.value / 1e6).toFixed(2)}M measured from `
      + `${minInfo.n}/${minInfo.pool} (${Math.round(minInfo.share * 100)}%) pre-arb 1-yr MLB deals`
      + (minInfo.isFloor === false ? ' [WARNING: mode is not the pool floor]' : '')
      + (minInfo.fallback ? ' [FALLBACK: no pre-arb pool, used the global modal salary]' : ''));
  } else {
    notes.push('league minimum NOT measurable — floor left free');
  }
  if (extensionsDropped) {
    notes.push(`${extensionsDropped} pre-free-agency extensions excluded that the `
      + 'integer-service-year filter would have admitted');
  }
  for (const [k, c] of [['pooled', pooled], ['hitter', hitter], ['pitcher', pitcher]]) {
    if (!c) continue;
    notes.push(`${k}: floor ${c.floorMode}`
      + (c.floorVsMin !== null ? ` (free intercept t=${c.floorVsMin.toFixed(2)} vs the minimum` : '')
      + (c.cvFloor && c.cvFloor.t !== null ? `, CV t=${c.cvFloor.t.toFixed(2)})` : ')')
      + `, shape ${c.shape}${c.curveRejected ? ` — curve REJECTED: ${c.curveRejected}` : ''}`);
  }
  for (const role of ['hitter', 'pitcher']) {
    if (roleCV[role]) {
      notes.push(`${role} line vs pooled line, out of sample: `
        + `${(roleCV[role].rmseRole / 1e6).toFixed(2)}M vs ${(roleCV[role].rmsePooled / 1e6).toFixed(2)}M `
        + `(paired t=${roleCV[role].t.toFixed(2)}) -> ${roleCV[role].useRole ? 'own line' : 'pooled line'}`);
    }
  }

  const live = {
    pooled, hitter, pitcher,
    perRole, useRoleLine, roleCV, slopeDiffT, ratioPH,
    sample,
    minSalary, minSalaryInfo: minInfo,
    svcYearDays: L, serviceBasis, extensionsDropped,
    notes,
    lowConfidence: !pooled || pooled.n < 30 || pooled.slope <= 0,
  };

  // Live vs banked. No threshold: the better-supported fit wins, and once the
  // live sample recovers past the banked one the bank stops being used on its
  // own. The provenance rides on the returned fit so the page can say which
  // line it is pricing with.
  const banked = opts && opts.banked && opts.banked.fit ? opts.banked : null;
  const liveN = marketFitSupport(live);
  const bankedN = banked ? marketFitSupport(banked.fit) : 0;
  const provenance = {
    used: bankedN > liveN ? 'banked' : 'live',
    liveN,
    bankedN: banked ? bankedN : null,
    bankedAt: banked ? banked.bankedAt || null : null,
  };
  if (provenance.used !== 'banked') return { ...live, provenance };

  return {
    ...banked.fit,
    provenance,
    notes: [
      `BANKED FIT IN USE — measured ${banked.bankedAt || 'earlier'} on `
      + `${bankedN} open-market signings. Today's live sample is only ${liveN} `
      + '(free agency reset ContractYr across the league). The live fit takes over '
      + 'again as soon as it rests on at least as many signings.',
      ...(banked.fit.notes || []),
    ],
  };
}

// ============================================================
// TIER-LOCAL MARKET (LOESS over comparable-WAR signings)
// ============================================================

// Standard LOESS conventions (labeled as such in the header): tricube kernel,
// span 0.4 (bandwidth = distance to the ceil(0.4*n)-th nearest neighbor,
// min 8 points). Everything else is measured from the sample itself.
const LOESS_SPAN = 0.4;
const LOESS_MIN_PTS = 8;

/**
 * Local linear regression of salary on WAR at x0 over the actual signings of
 * comparable-WAR players (tricube-weighted, kNN bandwidth). Returns
 * { mid, sd, nLocal } — the tier-local market price and the tier-local
 * dispersion of real signings — or null when the sample can't support it
 * (caller falls back to the global line).
 */
// The k-th smallest |x - x0| over the sample (k from 1). Selection, not a
// full sort: localFit runs about a dozen times per player on every list, and
// sorting the whole sample each time was most of the market pass. Same value
// as sorting and taking index k-1; a NaN distance takes the sort path, so
// that case also matches the sort exactly.
function kthDistance(sample, x0, k) {
  const n = sample.length;
  const d = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const v = Math.abs(sample[i].x - x0);
    if (v !== v) return sample.map(p => Math.abs(p.x - x0)).sort((a, b) => a - b)[k - 1];
    d[i] = v;
  }
  let lo = 0, hi = n - 1;
  const want = k - 1;
  while (lo < hi) {
    const pivot = d[(lo + hi) >> 1];
    let i = lo, j = hi;
    while (i <= j) {
      while (d[i] < pivot) i++;
      while (d[j] > pivot) j--;
      if (i <= j) { const t = d[i]; d[i] = d[j]; d[j] = t; i++; j--; }
    }
    if (want <= j) hi = j;
    else if (want >= i) lo = i;
    else break;
  }
  return d[want];
}

export function localFit(sample, x0raw) {
  const n = sample ? sample.length : 0;
  if (n < LOESS_MIN_PTS) return null;
  // NO EXTRAPOLATION: the market has never priced WAR outside the observed
  // signing range, so queries beyond it are evaluated AT the nearest observed
  // tier (extrapolating the local slope past the last data point invents
  // prices no one has ever paid).
  let minX = Infinity, maxX = -Infinity;
  for (const p of sample) { if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x; }
  // ABOVE the best contract ever signed, hand back to the fitted line (null => the
  // caller's fallback) instead of pinning to the top tier. Pinning made the entire top
  // of the market one number: TGS has never signed above 4.17 WAR, so Montero (5.69),
  // Guerrero (4.98), Oses (4.70) and everyone else were quoted an identical $34.37M
  // across a 1.5-win spread — no discrimination exactly where it matters most. Refusing
  // to extrapolate the LOCAL slope is right; freezing the price is not, and the line
  // carries the fitted $/WAR the rest of the system already prices on.
  // The LOW end still clamps: below the cheapest signing the tier IS the league minimum,
  // which is a real floor rather than an absence of evidence.
  if (x0raw > maxX) return null;
  const x0 = Math.max(minX, x0raw);
  const k = Math.min(n, Math.max(LOESS_MIN_PTS, Math.ceil(LOESS_SPAN * n)));
  const h = Math.max(kthDistance(sample, x0, k), 1e-6) * 1.0001; // include the k-th point
  let sw = 0, swx = 0, swy = 0, swxx = 0, swxy = 0;
  const pts = [];
  for (const p of sample) {
    const u = Math.abs(p.x - x0) / h;
    if (u >= 1) continue;
    const w = Math.pow(1 - u * u * u, 3); // tricube
    pts.push([p.x, p.y, w]);
    sw += w; swx += w * p.x; swy += w * p.y;
    swxx += w * p.x * p.x; swxy += w * p.x * p.y;
  }
  if (pts.length < 4 || sw <= 0) return null;
  const denom = sw * swxx - swx * swx;
  let a, b; // local line y = a + b*x
  if (Math.abs(denom) < 1e-9 * sw * sw) { b = 0; a = swy / sw; }
  else { b = (sw * swxy - swx * swy) / denom; a = (swy - b * swx) / sw; }
  // Weighted residual SD with an effective-sample-size df correction.
  let wssr = 0, sw2 = 0;
  for (const [x, y, w] of pts) {
    const e = y - (a + b * x);
    wssr += w * e * e; sw2 += w * w;
  }
  const effN = (sw * sw) / sw2;
  const sd = Math.sqrt((wssr / sw) * (effN / Math.max(effN - 2, 1)));
  // NO EXTRAPOLATION IN **y** (v3.1, added by the adversarial verify pass).
  // Clamping x0 into the observed range is not sufficient: a local LINE fitted
  // on a sparse, clumped neighbourhood can still be evaluated at a price no
  // comparable player received. Measured on the shipped data: BLM's hitter
  // curve returned $60.56M at 3.0 WAR — above the largest contract in the
  // entire league ($49.87M, Alex Lobato) — because the window's steep local
  // slope was extrapolated across the 2.76 -> 4.02 WAR gap. The local price is
  // therefore bounded by the actual signings that carried weight in its own
  // window: the tier-local market cannot quote more than the tier has ever
  // paid, nor less than it has ever paid. Bounds are DATA (observed AAVs), not
  // a tuned constant. NOTE: this bounds the level, it does NOT make the curve
  // monotone in WAR — see the header's LOESS note.
  let loY = Infinity, hiY = -Infinity;
  for (const [, y] of pts) { if (y < loY) loY = y; if (y > hiY) hiY = y; }
  const raw = a + b * x0;
  const mid = Math.min(hiY, Math.max(loY, raw));
  return { mid, sd, nLocal: pts.length, rawMid: raw, clamped: mid !== raw };
}

/**
 * The replaceable/scarcity boundary: the lowest WAR from which the LOCAL
 * market price stays MORE THAN 1 fitted residual SD ABOVE the fitted line all
 * the way up. Below it the line and the local market agree ("line value —
 * replaceable tier"); above it real prices depart the line ("market price —
 * scarcity tier"). Returns null when the local market never departs.
 *
 * v3 repair — the run must span at least MIN_TIER_XS distinct observed WAR
 * values. In v2 it routinely returned exactly the top observed WAR (a "tier"
 * containing one signing), which is not a market tier, it is an outlier; and
 * it now evaluates the LINE through `priceAt` so a fitted curve is compared
 * against itself rather than against a straight line it never used.
 */
const MIN_TIER_XS = 3;

export function computeScarcityBoundary(sample, line) {
  if (!sample || !sample.length || !line || !(line.residSD > 0)) return null;
  const at = typeof line.priceAt === 'function'
    ? line.priceAt
    : (w) => Math.max(0, line.floor + line.slope * w);
  const xs = [...new Set(sample.map(p => p.x))].sort((a, b) => a - b);
  let boundary = null, run = 0;
  for (let i = xs.length - 1; i >= 0; i--) {
    const lf = localFit(sample, xs[i]);
    if (!lf) break;
    if (lf.mid - at(xs[i]) > line.residSD) { boundary = xs[i]; run += 1; }
    else break;
  }
  return run >= MIN_TIER_XS ? boundary : null;
}

/**
 * Resolve the pricing context a given role uses:
 *   { slope, floor, curv, maxX, residSD,  — the fitted line/curve
 *     priceAt(w),              — the season price of WAR w (clamped, >= 0)
 *     sample,                  — the actual signings behind the tier-local fits
 *     boundary,                — replaceable/scarcity boundary WAR (or null)
 *     role, perRole, shape, floorMode }
 * v3: a role uses its OWN line only where fitFAMarket's out-of-sample test said
 * the split pays for itself (fit.useRoleLine[role]); otherwise the pooled line.
 * `override` ({ slope?, floor? } in $) is the page's manual what-if knob — it
 * replaces those coefficients of the LINE; the tier-local sample is data and is
 * not overridable.
 */
export function resolveRate(fit, role, override) {
  const usingRole = !!(fit && fit.useRoleLine && fit.useRoleLine[role] && fit[role]);
  const base = usingRole ? fit[role] : (fit && fit.pooled) || null;
  const slope = override && Number.isFinite(override.slope) ? override.slope : (base ? base.slope : 0);
  const floor = override && Number.isFinite(override.floor) ? override.floor : (base ? base.floor : 0);
  const curv = base ? (base.curv || 0) : 0;
  const residSD = base ? base.residSD : 0;
  const maxX = base && Number.isFinite(base.maxX) ? base.maxX : Infinity;
  const sample = fit && Array.isArray(fit.sample)
    ? (usingRole ? fit.sample.filter(s => s.role === role) : fit.sample)
    : [];
  const cell = { slope, floor, curv, maxX };
  const priceAt = (w) => cellPrice(cell, w);
  const boundary = computeScarcityBoundary(sample, { slope, floor, residSD, priceAt });
  return {
    slope, floor, curv, maxX, residSD, priceAt, sample, boundary, role,
    perRole: usingRole,
    shape: base ? base.shape : 'line',
    floorMode: base ? base.floorMode : 'free',
  };
}

// ============================================================
// AGED WAR PATH
// ============================================================

/**
 * Age a WAR value from ageNow to ageY on futureValue's getAgingFactor
 * schedule, RELATIVE to today: agedWAR(ageNow) === war exactly — the same
 * basis the FA fit regressed salary on. (futureValue's own applyAging is
 * anchored at the age-25 peak, which would discount even the current season
 * of a 27-year-old below his measured WAR and bias every valuation low.)
 * Negative-WAR handling mirrors applyAging: the decline is subtracted as an
 * absolute amount (reference max(0.5,|war|)) so bad players get worse, not
 * mysteriously better.
 */
export function agedWAR(war, ageNow, ageY) {
  const rel = getAgingFactor(ageY) / Math.max(getAgingFactor(ageNow), 1e-9);
  const ref = Math.max(0.5, Math.abs(war));
  return war - ref * (1 - Math.min(1, rel));
}

/**
 * Projected WAR for seasons y = 0..years-1 (year 0 = current season).
 *
 * ML PATH (a row with fv.expectedPath, futureValue.js 2026-09-25): the
 * internal WAR track of the expected path, the ML model's mean changes for
 * years 1..5 and the same curve rules after, so money is priced on the
 * expected outcome.
 *
 * MEASURED PATH (the DEV curve is loaded): the internal WAR track of the
 * row's fv.fullPath, for every age. Year 0 is today's WAR, growth runs to
 * 27 on the measured shape, and the measured decline follows, so an older
 * free agent is priced on the decline the curve measured. Past the path's
 * last age the curve's last mean keeps the decline going when the caller
 * passes ageCurve; without it the last value holds. A row without an
 * fv breakdown but with a curve gets the measured decline of its current
 * WAR (no growth).
 *
 * ASSUMED MODEL (no curve):
 * - Established players: relative aging of today's WAR (above).
 * - Developing prospects (pre-maturity, potential data + positive gap):
 *   follow futureValue's year-by-year development curve (already
 *   risk-adjusted), extended with relative aging past its projection window.
 *   The age < MATURITY_AGE guard matters: players 25+ can still carry stale
 *   potential columns, but futureValue itself grants them zero dev credit —
 *   routing them down the yearByYear path would price even their CURRENT
 *   season off the peak-anchored aging curve (below measured WAR), a
 *   systematic low bias vs the fit's current-WAR basis.
 */
export function agedWARPath(player, years, ageCurve) {
  const fv = player._fvBreakdown;
  const age = Math.round(parseFloat(player.Age) || 25);
  const war = fv ? fv.currentWAA : (getPlayerWAR(player) ?? 0);

  let measured = null;
  if (fv && fv.measured && Array.isArray(fv.expectedPath) && fv.expectedPath.length
      && Number.isFinite(fv.expectedPath[0].rawWAA)) {
    // ML rows (futureValue expectedPath, 2026-09-25): money prices on the
    // EXPECTED changes (the ML means), not the medians the display path
    // shows. A median understates a skewed outcome; a price must average it.
    measured = fv.expectedPath.map(x => ({ age: x.age, waa: x.rawWAA }));
  } else if (fv && fv.measured && Array.isArray(fv.fullPath) && fv.fullPath.length
      && Number.isFinite(fv.fullPath[0].rawWAA)) {
    measured = fv.fullPath.map(x => ({ age: x.age, waa: x.rawWAA }));
  } else if (!fv && ageCurve) {
    measured = measuredPath(ageCurve, age, war, war);
  }
  if (measured) {
    const shape = ageCurve ? curveShape(ageCurve) : null;
    const path = [];
    let last = measured[measured.length - 1];
    let waa = last.waa;
    for (let y = 0; y < years; y++) {
      if (y < measured.length) { path.push(measured[y].waa); continue; }
      const a = last.age + (y - measured.length) + 1;
      waa += shape ? Math.min(0, shape.mean(a - 1) ?? 0) : 0;
      path.push(waa);
    }
    return path;
  }

  const developing = !!(fv && fv.hasPotential
    && fv.potentialWAA - fv.currentWAA > 0
    && age < FV_DEFAULTS.MATURITY_AGE);
  const path = [];
  for (let y = 0; y < years; y++) {
    const ageY = age + y;
    if (developing && fv.yearByYear && fv.yearByYear.length) {
      const yr = fv.yearByYear[y];
      if (yr) { path.push(yr.rawWAA); continue; }
      const last = fv.yearByYear[fv.yearByYear.length - 1];
      path.push(agedWAR(last.rawWAA, last.age, ageY));
      continue;
    }
    path.push(agedWAR(war, age, ageY));
  }
  return path;
}

// ============================================================
// PLAYER VALUATION
// ============================================================

const r2dp = (v) => Math.round(v * 100) / 100;

/**
 * Value a player against the fitted market line.
 *
 * @param {Object} player - player row (ideally with _fvBreakdown attached)
 * @param {{slope:number, floor:number, residSD?:number}} rate - resolved fit
 *        (resolveRate). NOT a bare number any more.
 * @param {{ageCurve?:Object}} [opts] - the measured DEV curve (age_curve.json)
 *        for agedWARPath; the row's own measured path is used either way.
 */
export function calculatePlayerValue(player, rate, opts = {}) {
  const ageCurve = opts && opts.ageCurve ? opts.ageCurve : null;
  const slope = rate && Number.isFinite(rate.slope) ? rate.slope : 0;
  const floor = rate && Number.isFinite(rate.floor) ? rate.floor : 0;
  const curv = rate && Number.isFinite(rate.curv) ? rate.curv : 0;
  const maxX = rate && Number.isFinite(rate.maxX) ? rate.maxX : Infinity;
  const residSD = rate && Number.isFinite(rate.residSD) ? rate.residSD : 0;
  const sample = rate && Array.isArray(rate.sample) ? rate.sample : [];
  const boundary = rate && Number.isFinite(rate.boundary) ? rate.boundary : null;

  const fv = player._fvBreakdown;
  const age = Math.round(parseFloat(player.Age) || 25);
  const war = fv ? fv.currentWAA : (getPlayerWAR(player) ?? 0);
  const price = toNum(player.Price) || 0;
  const D = 1 - FV_DEFAULTS.DISCOUNT_RATE; // 0.97/yr, futureValue's rate
  const isProspect = !!(fv && fv.hasPotential && fv.yearsTilPeak > 0);

  // LINE value of a season of WAR w — floored at the walk-away point ($0) and
  // never extrapolated above the top WAR the market has actually priced.
  const seasonValue = rate && typeof rate.priceAt === 'function'
    ? rate.priceAt
    : (w) => cellPrice({ slope, floor, curv, maxX }, w);
  // TIER-LOCAL market price of a season of WAR w: LOESS over comparable-WAR
  // signings; falls back to the line when the sample can't support a local
  // fit. Returns { mid, sd, local }.
  const marketAt = (w) => {
    const lf = localFit(sample, w);
    return lf
      ? { mid: Math.max(0, lf.mid), sd: lf.sd, local: true }
      : { mid: seasonValue(w), sd: residSD, local: false };
  };

  // --- Year-0 (current season) ---
  // "line value — replaceable tier" economy: value/surplus vs the fitted line.
  const annualValue = Math.round(seasonValue(war));
  const surplus = Math.round(annualValue - price);
  // "market price — scarcity tier" economy: what comparable-WAR players
  // actually sign for (tier-local fit).
  const mkt0 = marketAt(war);
  const marketPrice = Math.round(mkt0.mid);
  const marketSurplus = Math.round(mkt0.mid - price);
  const tier = boundary !== null && war >= boundary ? 'scarcity' : 'replaceable';

  // --- Multi-year contract surplus over the remaining SalarySchedule ---
  let contract = null;
  const sched = Array.isArray(player.SalarySchedule)
    ? player.SalarySchedule.filter(Number.isFinite)
    : [];
  if (sched.length && slope > 0) {
    const path = agedWARPath(player, sched.length, ageCurve);
    let totSalary = 0, totValue = 0, totSurplus = 0;
    const years = sched.map((salary, y) => {
      const w = path[y];
      const value = seasonValue(w);
      const disc = Math.pow(D, y);
      const discSurplus = (value - salary) * disc;
      totSalary += salary;
      totValue += value * disc;
      totSurplus += discSurplus;
      return {
        year: y + 1,
        age: age + y,
        salary,
        agedWAR: r2dp(w),
        value: Math.round(value),
        surplus: Math.round(value - salary),
        discSurplus: Math.round(discSurplus),
      };
    });
    contract = {
      years,
      yearsRemaining: sched.length,
      totalSalary: Math.round(totSalary),
      totalValue: Math.round(totValue),
      surplus: Math.round(totSurplus),
    };
  }

  // --- Fair offer (v2: TIER-LOCAL) — the local market price at the mean aged
  // WAR over the proposed years, band = +/- 1 LOCAL residual SD (the fitted
  // dispersion of comparable-WAR signings, not the global one). Default
  // horizon: THIS player's remaining control (serviceTime.controlWindow),
  // clipped by career end (MAX_CAREER_AGE). It used to be a flat 6 for
  // everyone, which quoted a 5.1-service veteran a six-year AAV he can only be
  // held one year for. Floored at 1: an offer is at least the season in front
  // of you, which is also the horizon for a player already past free agency.
  const control = controlWindow(player);
  // ONE YEAR, for everybody (user directive). The headline offer has to be COMPARABLE
  // down a column, and a per-player horizon is not: it ran 1..6 years, with every age
  // from 25 to 28 containing all six. Worse, it pointed the wrong way — a shorter
  // horizon averages in LESS decline, so an older player was quoted a HIGHER AAV than an
  // identical younger one. Quoting one season of him puts every player on one basis and
  // removes the variable entirely.
  // Pricing an actual multi-year deal still lives in offerByLength below, which quotes
  // 1..maxLen years side by side — that is the place to choose a term, not the headline.
  const offerYears = 1;
  // The table runs to 8 years, but a long extension can control a young player
  // for more than that; the horizon row has to exist or meanWAR(offerYears)
  // would divide a shorter path by the longer horizon and understate it.
  const maxLen = Math.max(1, Math.min(Math.max(8, offerYears), FV_DEFAULTS.MAX_CAREER_AGE - age));
  const offerPath = agedWARPath(player, maxLen, ageCurve);
  const meanWAR = (len) => offerPath.slice(0, len).reduce((s, w) => s + w, 0) / len;

  const offerMeanWAR = meanWAR(offerYears);
  const offerMkt = marketAt(offerMeanWAR);
  const offerMid = Math.round(offerMkt.mid);
  const offerFloor = Math.max(0, Math.round(offerMkt.mid - offerMkt.sd));
  const offerCeiling = Math.round(offerMkt.mid + offerMkt.sd);

  // Fair AAV by proposed contract length (detail card): 1..maxLen years,
  // each length priced at ITS OWN tier (low/high = +/- 1 local SD).
  const offerByLength = [];
  for (let len = 1; len <= maxLen; len++) {
    const m = meanWAR(len);
    const mk = marketAt(m);
    const aav = Math.round(mk.mid);
    offerByLength.push({
      years: len, meanWAR: r2dp(m), aav, total: aav * len,
      low: Math.max(0, Math.round(mk.mid - mk.sd)),
      high: Math.round(mk.mid + mk.sd),
    });
  }

  // --- Peak (ceiling) value: what a season at expected peak WAR trades for
  // in ITS tier (a peak season is bought at the market, so tier-local) ---
  const peakWAR = fv
    ? Math.max(fv.expectedPeakWAA ?? war, fv.peakProjectedWAA ?? war)
    : war;
  const peakMkt = marketAt(peakWAR);
  const futureAnnualValue = Math.round(peakMkt.mid);
  const futureOfferFloor = Math.max(0, Math.round(peakMkt.mid - peakMkt.sd));
  const futureOfferMid = futureAnnualValue;
  const futureOfferCeiling = Math.round(peakMkt.mid + peakMkt.sd);

  // --- Career total (reference): discounted sum of season values over the
  // FV projection window. The old extra 0.08*yearsTilPeak prospect discount
  // is REMOVED — development risk is already priced inside futureValue's
  // risk factor and dev curve (labeled heuristic there, not re-discounted
  // here). ---
  let totalValue = 0;
  const yearlyValues = (fv && fv.yearByYear ? fv.yearByYear : []).map((yr, y) => {
    const value = seasonValue(yr.rawWAA) * Math.pow(D, y);
    totalValue += value;
    return {
      age: yr.age,
      rawWAA: yr.rawWAA,
      discountedWAA: yr.discountedWAA,
      yearValue: Math.round(value),
    };
  });
  totalValue = Math.round(totalValue);
  const productiveYears = yearlyValues.filter(y => y.rawWAA > 0).length || 1;

  return applyHealthDiscount({
    // year-0 — line economy ("line value — replaceable tier")
    annualValue, surplus,
    // year-0 — tier-local economy ("market price — scarcity tier")
    marketPrice, marketSurplus, tier,
    localSD: Math.round(mkt0.sd), isLocalPrice: mkt0.local,
    // multi-year contract (line economy)
    contract,
    // fair offer (tier-local)
    offerFloor, offerMid, offerCeiling, offerYears,
    offerMeanWAR: r2dp(offerMeanWAR), offerByLength,
    // peak (tier-local)
    futureAnnualValue, futureOfferFloor, futureOfferMid, futureOfferCeiling,
    // career reference (line economy)
    totalValue, adjustedValue: totalValue, yearlyValues, productiveYears,
    // context
    currentPrice: price, warNow: r2dp(war), isProspect,
    control,
    rateUsed: {
      slope, floor, curv, maxX, residSD,
      shape: rate ? rate.shape : 'line',
      floorMode: rate ? rate.floorMode : 'free',
      role: rate ? rate.role : undefined,
      perRole: rate ? !!rate.perRole : false,
      boundary,
    },
  }, player);
}

// Convenience wrappers (API compatible with the hooks)
export function calculateHitterValue(player, rate, opts) {
  return calculatePlayerValue(player, rate, opts);
}
export function calculatePitcherValue(player, rate, opts) {
  return { ...calculatePlayerValue(player, rate, opts), role: isBetterAsRP(player) ? 'RP' : 'SP' };
}

// ============================================================
// MARKET ANALYSIS (Market Value page)
// ============================================================

/**
 * Analyze the salary market for the page: the FA fit plus WAR-based scatter
 * points, buckets and tiers. All in WAR currency (offsets included).
 */
export function analyzeMarket(hitters, pitchers, opts) {
  const fit = fitFAMarket(hitters, pitchers, opts);
  const faKeys = new Set(fit.sample.map(s => `${s.name}|${s.org}`));

  const allPlayers = [...(hitters || []), ...(pitchers || [])];
  const dataPoints = [];
  for (const p of allPlayers) {
    if (p.Lev !== 'MLB') continue;
    const price = toNum(p.Price);
    if (price === null || price <= 0) continue;
    const war = getPlayerWAR(p);
    if (war === null) continue;
    dataPoints.push({
      name: p.Name, age: p.Age, pos: p.POS, org: p.ORG,
      war,
      price,                          // this season's salary (scatter y)
      aav: contractAAV(p) ?? price,   // what the deal actually cost per year
      isFA: faKeys.has(`${p.Name}|${p.ORG}`),
      isPreArb: fit.minSalary ? price <= fit.minSalary * 1.02 : price < 1_000_000,
      fvScale: p._fvScale, futureValue: p._futureValue,
    });
  }

  const buckets = buildWARBuckets(dataPoints);
  const tiers = buildMarketTiers(dataPoints.filter(d => d.isFA));

  return {
    fit,
    dataPoints,
    faCount: fit.sample.length,
    mlbPaidCount: dataPoints.length,
    buckets,
    tiers,
  };
}

function buildWARBuckets(dataPoints) {
  const bucketDefs = [
    { label: '<1 WAR', min: -Infinity, max: 1 },
    { label: '1-2', min: 1, max: 2 },
    { label: '2-3', min: 2, max: 3 },
    { label: '3-4', min: 3, max: 4 },
    { label: '4-5', min: 4, max: 5 },
    { label: '5+', min: 5, max: Infinity },
  ];
  return bucketDefs.map(def => {
    const players = dataPoints.filter(d => d.war >= def.min && d.war < def.max);
    const fa = players.filter(d => d.isFA);
    // FA buckets describe SIGNINGS, so they average the AAV the deal cost —
    // the same basis the line is fitted on — not just year 1.
    const totalPrice = fa.reduce((s, d) => s + (d.aav ?? d.price), 0);
    return {
      ...def,
      count: players.length,
      faCount: fa.length,
      avgPrice: fa.length > 0 ? Math.round(totalPrice / fa.length) : 0,
    };
  });
}

function buildMarketTiers(faPoints) {
  if (faPoints.length === 0) return [];
  const sorted = [...faPoints].sort((a, b) => b.war - a.war);
  const n = sorted.length;
  const superstarCut = Math.max(1, Math.floor(n * 0.10));
  const starCut = Math.max(superstarCut + 1, Math.floor(n * 0.35));
  function tierStats(players, label) {
    const totalPrice = players.reduce((s, d) => s + (d.aav ?? d.price), 0);
    return {
      label,
      count: players.length,
      minWAR: players.length > 0 ? Math.min(...players.map(d => d.war)) : 0,
      maxWAR: players.length > 0 ? Math.max(...players.map(d => d.war)) : 0,
      avgPrice: players.length > 0 ? Math.round(totalPrice / players.length) : 0,
    };
  }
  return [
    tierStats(sorted.slice(0, superstarCut), 'Superstar (Top 10%)'),
    tierStats(sorted.slice(superstarCut, starCut), 'Star (10-35%)'),
    tierStats(sorted.slice(starCut), 'Regular (35-100%)'),
  ];
}

// ============================================================
// FORMATTING
// ============================================================

export function formatMoney(value) {
  if (value === null || value === undefined) return '-';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '-';
  const abs = Math.abs(num);
  const sign = num < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  return `${sign}$${abs.toLocaleString()}`;
}
