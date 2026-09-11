/**
 * TGS Future Value Calculator v2
 *
 * Research-backed model using actual WAA data from the TGS sheets.
 *
 * Key design decisions (backed by data analysis + sabermetric research):
 * - Development S-curve (logistic) with maturity at age 25 (OOTP default)
 * - No plateau: INTERIM decline schedule from age 26 (~6%/yr, 9%/yr past 31) —
 *   see FV_DEFAULTS; unmeasured until the aging harness runs (audit Phase C)
 * - Valuation counts a FIXED number of controlled seasons from expected
 *   arrival (D5 audit fix) — the window no longer shrinks for young prospects
 * - Risk factor 0.80-0.95 range (generous — sheets already discount via conservative potential ratings)
 * - 3% annual time discount (mild — we're rating talent, not contract surplus)
 * - NO positional scarcity bonus (WAA already includes defense)
 * - Percentile-based 20-80 FV scale calibration
 *
 * Data insights:
 * - Potential data only exists for ages 16-23 (hard cutoff)
 * - Only 3.2% of hitters currently above 0 WAA; 20% of prospects have potential >= 0
 * - Development GAP: ~8 WAA at age 16, ~2 WAA at age 23 (hitters)
 * - 56 hitters (1.5%) have potential >= 3.0 WAA (elite tier)
 *
 * Sources:
 * - FanGraphs aging curve research (peak ~27, decline ~0.5 WAR/yr after 30)
 * - Yale study (Fair, April 2025): peak performance age ~27.5 hitters, ~26.5 pitchers
 * - OOTP mechanics: development stops at 25, aging curve kicks in ~30
 * - FanGraphs prospect valuation: 8% discount for contract surplus (we use 3% for talent rating)
 */

// ============================================================
// MODEL PARAMETERS — all tunable from Dev Analysis page
// ============================================================

import { replacementOffset } from './leagueCalib.js';
import { measuredTrajectory } from './ageCurve.js';

export const FV_DEFAULTS = {
  // Development curve (Gap Factor)
  MATURITY_AGE: 25,       // Age when development stops (OOTP default)
  GAP_MAX: 0.95,          // Max fraction of potential gap reached at maturity
  GAP_STEEPNESS: 0.6,     // Logistic curve steepness (higher = sharper S)

  // Risk factor
  RISK_FLOOR: 0.80,       // Minimum risk credit (worst-case percentile)
  RISK_CEILING: 0.95,     // Maximum risk credit (best-case percentile)

  // Aging curve — INTERIM SCHEDULE (user directive, 2026-08-05) until the aging
  // harness measures true curves (audit Phase C: real-league clone, dev ON,
  // per-year ratings exports). No aging parameter here has ever been validated —
  // the calibration league is all-age-27 with development frozen.
  // Decline ONSET is ~age 26 (OOTP default aging), NOT the old cliff-at-30
  // assumption: a modest 6%/yr from 26, with a soft late-career acceleration
  // (9%/yr from 32) instead of the uncalibrated hard 12%/yr cliff at 30.
  // Deliberately conservative: young players aren't punished, old players
  // aren't flattered.
  PEAK_END: 25,           // last flat year — decline starts at age 26 (OOTP default aging)
  DECLINE_RATE: 0.06,     // annual decline 26+ (INTERIM — unmeasured)
  CLIFF_AGE: 31,          // last 6%/yr year; acceleration from 32 (INTERIM; was a hard cliff at 30)
  CLIFF_RATE: 0.09,       // annual decline past CLIFF_AGE (INTERIM; was 12%)

  // Time value
  DISCOUNT_RATE: 0.03,    // Annual discount rate (3%)

  // Projection window
  MAX_CAREER_AGE: 34,     // Don't project beyond this age (shorter careers)
  // FALLBACK ONLY. Callers pass the player's real remaining control
  // (serviceTime.controlWindow); this is what a row with neither service nor
  // contract data falls back to — a full pre-free-agency window (6 service
  // years is the league rule).
  DEFAULT_YEARS_OF_CONTROL: 6,
};

// ============================================================
// GAP FACTOR — Logistic S-curve for development
// ============================================================

/**
 * Compute the development gap factor at a given age.
 * Returns 0 to GAP_MAX, following a logistic S-curve.
 *
 * At age 16: ~0.05 (barely developed)
 * At inflection (~20.5): ~GAP_MAX/2 (50% developed)
 * At maturity (25): ~GAP_MAX (95% developed)
 *
 * @param {number} age - Player's current age
 * @param {Object} [params] - Override default parameters
 * @returns {number} Gap factor (0 to GAP_MAX)
 */
export function getGapFactor(age, params = {}) {
  const {
    MATURITY_AGE = FV_DEFAULTS.MATURITY_AGE,
    GAP_MAX = FV_DEFAULTS.GAP_MAX,
    GAP_STEEPNESS = FV_DEFAULTS.GAP_STEEPNESS,
  } = params;

  // Inflection point: midpoint of typical development range (16 to MATURITY_AGE)
  const inflectionAge = (16 + MATURITY_AGE) / 2;

  // Raw logistic
  const raw = 1 / (1 + Math.exp(-GAP_STEEPNESS * (age - inflectionAge)));

  // Normalize: we want gapFactor(MATURITY_AGE) ≈ GAP_MAX and gapFactor(16) ≈ small
  const rawAtMaturity = 1 / (1 + Math.exp(-GAP_STEEPNESS * (MATURITY_AGE - inflectionAge)));
  const rawAt16 = 1 / (1 + Math.exp(-GAP_STEEPNESS * (16 - inflectionAge)));

  // Scale raw to [0, GAP_MAX] range based on the 16-to-maturity window
  const normalized = (raw - rawAt16) / (rawAtMaturity - rawAt16);
  return Math.max(0, Math.min(GAP_MAX, normalized * GAP_MAX));
}

// ============================================================
// AGING FACTOR — Smooth decline curve
// ============================================================

/**
 * Compute the aging factor at a given age.
 * Returns 1.0 through PEAK_END, declining after.
 *
 * INTERIM schedule (see FV_DEFAULTS):
 *   ≤25: 1.0
 *   26 through CLIFF_AGE (31): decline at DECLINE_RATE (6%) per year
 *   past CLIFF_AGE: decline at CLIFF_RATE (9%) per year
 *
 * @param {number} age - Player's age
 * @param {Object} [params] - Override default parameters
 * @returns {number} Aging factor (0 to 1.0)
 */
export function getAgingFactor(age, params = {}) {
  const {
    PEAK_END = FV_DEFAULTS.PEAK_END,
    DECLINE_RATE = FV_DEFAULTS.DECLINE_RATE,
    CLIFF_AGE = FV_DEFAULTS.CLIFF_AGE,
    CLIFF_RATE = FV_DEFAULTS.CLIFF_RATE,
  } = params;

  if (age <= PEAK_END) return 1.0;

  if (age <= CLIFF_AGE) {
    return Math.pow(1 - DECLINE_RATE, age - PEAK_END);
  }

  // Factor at cliff age, then steeper decline beyond
  const atCliff = Math.pow(1 - DECLINE_RATE, CLIFF_AGE - PEAK_END);
  return atCliff * Math.pow(1 - CLIFF_RATE, age - CLIFF_AGE);
}

/**
 * Apply aging to a WAA value correctly for both positive and negative WAA.
 *
 * The raw agingFactor is a multiplier (0 to 1), which works for positive WAA
 * (e.g., 5 * 0.73 = 3.65, a decline). But for negative WAA it breaks:
 * -3 * 0.73 = -2.19 looks like improvement.
 *
 * Fix: compute the WAA lost as an absolute amount, then subtract it.
 * For positive WAA this gives identical results to the multiplicative model.
 * For negative WAA it correctly makes the player worse.
 *
 * @param {number} peakWAA - The player's expected peak WAA
 * @param {number} futureAge - Age to project to
 * @param {Object} [params] - Override default parameters
 * @returns {number} Projected WAA at futureAge
 */
export function applyAging(peakWAA, futureAge, params = {}) {
  const af = getAgingFactor(futureAge, params);
  // Use at least 0.5 as reference so even 0-WAA players decline slightly
  const reference = Math.max(0.5, Math.abs(peakWAA));
  return peakWAA - reference * (1 - af);
}

// ============================================================
// RISK FACTOR — Development credit
// ============================================================

/**
 * Compute the risk-adjusted credit factor from a percentile.
 * Used by the Dev Analysis percentile table for what-if exploration.
 *
 *   percentile 0 → RISK_FLOOR
 *   percentile 100 → RISK_CEILING
 *
 * @param {number} [percentile=50] - Development percentile (0-100)
 * @param {Object} [params] - Override default parameters
 * @returns {number} Risk factor
 */
export function getRiskFactor(percentile = 50, params = {}) {
  const {
    RISK_FLOOR = FV_DEFAULTS.RISK_FLOOR,
    RISK_CEILING = FV_DEFAULTS.RISK_CEILING,
  } = params;

  const t = Math.max(0, Math.min(100, percentile)) / 100;
  return RISK_FLOOR + t * (RISK_CEILING - RISK_FLOOR);
}

/**
 * Compute a per-player risk factor based on their development state.
 *
 * Two components that BOTH inform certainty:
 *
 * 1. Development progress (age-based):
 *    - How far along the S-curve is this player?
 *    - A 22-year-old near maturity has less uncertainty than a 16-year-old.
 *    - progress = gapFactor(age) / GAP_MAX → 0 to 1
 *    - Players at/past maturity → progress = 1 (fully developed)
 *
 * 2. Gap magnitude (skill-based):
 *    - Larger gaps have more uncertainty — more things have to go right.
 *    - A player closing a 2 WAA gap is much safer than one closing 13 WAA.
 *    - We map gap size to a 0-1 penalty where bigger gaps pull risk down.
 *    - GAP_RISK_SCALE controls sensitivity (default: 10 WAA = max penalty).
 *
 * Final risk = RISK_FLOOR + combinedScore * (RISK_CEILING - RISK_FLOOR)
 * where combinedScore = average of progress and gap certainty, 0 to 1.
 *
 * For established players (no gap), returns RISK_CEILING (no development risk).
 *
 * @param {number} age - Player's current age
 * @param {number} gap - potentialWAA - currentWAA (the development gap)
 * @param {boolean} hasPotential - Whether the player has potential data
 * @param {Object} [params] - Override default parameters
 * @returns {number} Risk factor between RISK_FLOOR and RISK_CEILING
 */
export function getPlayerRisk(age, gap, hasPotential, params = {}) {
  const p = { ...FV_DEFAULTS, ...params };

  // Established players have no development uncertainty
  if (!hasPotential || gap <= 0) return p.RISK_CEILING;

  // 1. Development progress: how far along the S-curve
  const gapFactorNow = getGapFactor(age, p);
  const progress = Math.min(1, gapFactorNow / p.GAP_MAX);

  // 2. Gap certainty: smaller gaps are safer bets
  //    gap=0 → certainty=1 (no gap to close), gap=10+ → certainty≈0
  const GAP_RISK_SCALE = 10; // WAA gap at which certainty bottoms out
  const gapCertainty = Math.max(0, 1 - (gap / GAP_RISK_SCALE));

  // Combine: 60% weight on progress (age is the biggest risk factor),
  //          40% weight on gap size
  const combinedScore = 0.6 * progress + 0.4 * gapCertainty;

  return p.RISK_FLOOR + combinedScore * (p.RISK_CEILING - p.RISK_FLOOR);
}

// ============================================================
// WAA EXTRACTION from player data
// ============================================================

/**
 * Get the best current and best potential VALUE from player data.
 *
 * audit M5: values are WAR-style — each candidate column carries its role's
 * MEASURED replacement offset (leagueCalib.js: hitter/SP/RP, per league via
 * player.League) before taking the max. WAA compared an average RP (0) to an
 * average hitter (0) as equals; in WAR the hitter is ~+1 win over what an org
 * can roster for free while the RP is ~+0.2 — so cross-type FV ordering now
 * matches real scarcity. Raw FV 0 now genuinely means "replacement level"
 * (which is what the FV-40 anchor always claimed).
 */
function getPlayerWAAValues(player) {
  // _appLeague is stamped by usePlayerData (the raw 'League' field is a numeric
  // StatsPlus id); unknown/missing falls back to TGS inside leagueCalib.
  const league = player._appLeague;
  const hOff = replacementOffset(league, 'hitter');
  const spOff = replacementOffset(league, 'sp');
  const rpOff = replacementOffset(league, 'rp');
  // Blended (wtd) columns ONLY — never a single platoon split. Including 'Max WAA vR'
  // here handed every L/S batter his good-side split as "current" (a 3.5vR/0.1vL
  // platoon bat was valued at 3.5), while R batters got the honest blend — an
  // asymmetric handedness bias caught by the user on the FV board (Wisner case).
  const currentWAACols = [['Max WAA wtd', hOff, 'hitter'],
                          ['WAA wtd', spOff, 'sp'], ['WAA wtd RP', rpOff, 'rp']];
  const potentialWAACols = [['MAX WAA P', hOff, 'hitter'],
                            ['WAP', spOff, 'sp'], ['WAP RP', rpOff, 'rp']];

  let currentWAA = -Infinity;
  let offsetUsed = hOff;   // the role offset behind currentWAA (UI subtracts it for WAA display)
  let currentRole = 'hitter';
  for (const [col, off, role] of currentWAACols) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val + off > currentWAA) { currentWAA = val + off; offsetUsed = off; currentRole = role; }
  }
  if (currentWAA === -Infinity) currentWAA = 0;

  // The CURRENT argmax and the POTENTIAL argmax are taken independently, so they
  // can land on DIFFERENT ROLES — and routinely do. The sheet grades a starter
  // over ~800 BF and a reliever over ~300, so a teenage arm is -8.1 WAA as an SP
  // but only -2.9 as an RP: RP wins "current" while his ceiling (WAP > WAP RP)
  // makes SP win "potential". That is a coherent statement in WAR (both roles are
  // priced against freely-available talent) and the scoring math is right to use
  // it. But it means ONE offset cannot convert both ends back to WAA — which is
  // exactly the bug this field fixes. potentialOffsetUsed is the role offset
  // behind potentialWAA; when there is no potential data the two coincide.
  let potentialWAA = null;
  let potentialOffsetUsed = null;
  let potentialRole = null;
  for (const [col, off, role] of potentialWAACols) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && (potentialWAA === null || val + off > potentialWAA)) {
      potentialWAA = val + off;
      potentialOffsetUsed = off;
      potentialRole = role;
    }
  }

  // If no potential data (age 24+), potential = current (no development upside)
  const hasPotential = potentialWAA !== null;
  if (!hasPotential) {
    potentialWAA = currentWAA;
    potentialOffsetUsed = offsetUsed;
    potentialRole = currentRole;
  }

  return { currentWAA, potentialWAA, hasPotential,
           offsetUsed, potentialOffsetUsed, currentRole, potentialRole };
}

// ============================================================
// FV SCALE — Percentile-based 20-80 calibration
// ============================================================

/**
 * Convert raw future value (cumulative projected WAA) to 20-80 scouting scale.
 * Uses piecewise linear interpolation between calibration anchors.
 *
 * Calibrated against actual data distribution:
 * - FV 80: elite/generational (top ~0.1%)
 * - FV 70: franchise player (top ~0.5%)
 * - FV 60: solid regular (top ~5%)
 * - FV 50: fringe regular (top ~20%)
 * - FV 40: replacement level
 * - FV 20: no future value
 */
const FV_ANCHORS = [
  { rawFV: -15, fv: 20 },
  { rawFV: -8,  fv: 25 },
  { rawFV: -3,  fv: 30 },
  { rawFV: 0,   fv: 40 },
  { rawFV: 2,   fv: 45 },
  { rawFV: 5,   fv: 50 },
  { rawFV: 9,   fv: 55 },
  { rawFV: 14,  fv: 60 },
  { rawFV: 20,  fv: 65 },
  { rawFV: 28,  fv: 70 },
  { rawFV: 45,  fv: 80 },
];

function rawFVtoScale(rawFV) {
  // Below minimum anchor
  if (rawFV <= FV_ANCHORS[0].rawFV) return FV_ANCHORS[0].fv;

  // Above maximum anchor
  const last = FV_ANCHORS[FV_ANCHORS.length - 1];
  if (rawFV >= last.rawFV) return last.fv;

  // Interpolate between anchors
  for (let i = 0; i < FV_ANCHORS.length - 1; i++) {
    const lo = FV_ANCHORS[i];
    const hi = FV_ANCHORS[i + 1];
    if (rawFV >= lo.rawFV && rawFV < hi.rawFV) {
      const t = (rawFV - lo.rawFV) / (hi.rawFV - lo.rawFV);
      return Math.round(lo.fv + t * (hi.fv - lo.fv));
    }
  }

  return 40; // fallback
}

// ============================================================
// MAIN CALCULATOR
// ============================================================

/**
 * Calculate Future Value for a player using WAA data from the TGS sheets.
 *
 * @param {Object} player - Player data object with WAA columns
 * @param {number} [yearsOfControl] - Years of team control remaining
 *        (serviceTime.controlWindow). Omitted -> DEFAULT_YEARS_OF_CONTROL.
 * @param {Object} [params] - Override model parameters (for Dev Analysis tuning)
 * @returns {Object} Future value breakdown
 */
export function calculateFutureValue(player, yearsOfControl, params = {}) {
  const p = { ...FV_DEFAULTS, ...params };
  // A caller-supplied 0 is MEANINGFUL (a player already past free agency) and
  // must not fall back to the default — the window clamp below still keeps the
  // season in front of you, which is the only thing an expiring player is.
  const yoc = Number.isFinite(yearsOfControl) ? yearsOfControl : p.DEFAULT_YEARS_OF_CONTROL;
  const age = parseFloat(player.Age) || 25;

  // Extract WAA values
  const waaVals = getPlayerWAAValues(player);
  const { currentWAA, potentialWAA, hasPotential } = waaVals;

  // Per-player risk factor based on age + gap size
  const gap = potentialWAA - currentWAA;
  const riskFactor = getPlayerRisk(age, gap, hasPotential, p);

  // Expected peak WAA ("Proj Potential" — what we think they'll actually reach).
  //
  // MEASURED PATH (DORMANT — no caller passes ageCurve yet): when a caller
  // supplies the measured age curve (engine/agecurve_fit.py, refreshed every
  // ratings pull), iterate the MEASURED per-age gap-closure rates from his age
  // to 25. This is what separates a nearly-there 21-year-old from a massively
  // underdeveloped 23-year-old with the same ceiling. No invented constants on
  // this path. WHY DORMANT (user, 2026-08-26): the archive's only window so
  // far predates the league's first full tracked development cycle — offseason
  // dev labs still running, and the commissioner mass-toggles adjusted ratings
  // in this period — so the measured closure rates aren't development yet.
  // Enable by passing { ageCurve } from usePlayersWithFV + PlayerDetail once a
  // full clean dev cycle is in the archive.
  //
  // LIVE PATH (until then, and for a league with no curve at all):
  // the original assumed model — GAP_MAX x riskFactor with current floored
  // at 0 so a teenager's rookie-ball negative WAA doesn't drag his ceiling.
  //
  // Either way development ends when a player TURNS 25 (league rule,
  // user-stated): 25+ gets NO growth credit — his projected peak is what he
  // is now. (measuredTrajectory returns null at 25+, so both paths agree.)
  const devCredit = age >= 25 ? 0 : 1;
  const mTraj = (p.ageCurve && hasPotential && gap > 0 && devCredit > 0)
    ? measuredTrajectory(p.ageCurve, age, currentWAA, potentialWAA)
    : null;
  const baseForPeak = Math.max(currentWAA, 0);
  const developedPeak = baseForPeak + (potentialWAA - baseForPeak) * p.GAP_MAX * riskFactor;
  const expectedPeakWAA = mTraj
    ? mTraj[mTraj.length - 1].waa
    : (hasPotential && gap > 0
        ? currentWAA + (developedPeak - currentWAA) * devCredit
        : currentWAA);

  // ---- PARALLEL WAA (vs average) TRACK — display only ----
  // The boards display WAA by user directive while this engine computes in WAR
  // (its FV anchors are calibrated there and the $ layer needs a replacement
  // zero). Converting back used to be "subtract offsetUsed", which is only valid
  // when the current and potential argmaxes land on the SAME role. They don't for
  // ~1/3 of pitchers (RP wins current, SP wins potential — see getPlayerWAAValues),
  // and subtracting the RP offset (0.31) from an SP-anchored peak left ~2.2 wins of
  // starter replacement level inside a column labelled "WAA".
  //
  // Rather than reverse-engineer a blended offset, recompute the SAME formulas on
  // WAA inputs. Every quantity below mirrors a WAR line above, so the two tracks
  // cannot drift apart. Note the 0-WAR floor in baseForPeak is REPLACEMENT LEVEL
  // for the role the peak is anchored on, which in WAA is -potentialOffsetUsed.
  const oCur = Number.isFinite(waaVals.offsetUsed) ? waaVals.offsetUsed : 0;
  const oPot = Number.isFinite(waaVals.potentialOffsetUsed) ? waaVals.potentialOffsetUsed : oCur;
  const currentAsWAA = currentWAA - oCur;
  const potentialAsWAA = potentialWAA - oPot;
  const baseAsWAA = baseForPeak === currentWAA ? currentAsWAA : -oPot;
  const developedPeakAsWAA = baseAsWAA + (potentialAsWAA - baseAsWAA) * p.GAP_MAX * riskFactor;
  // measured path: same iteration on the display-WAA inputs (closure applies to
  // the gap, so the two tracks stay in step; drift years use the same rates)
  const mTrajAs = mTraj
    ? measuredTrajectory(p.ageCurve, age, currentAsWAA, potentialAsWAA)
    : null;
  const expectedPeakAsWAA = mTrajAs
    ? mTrajAs[mTrajAs.length - 1].waa
    : (hasPotential && gap > 0
        ? currentAsWAA + (developedPeakAsWAA - currentAsWAA) * devCredit
        : currentAsWAA);

  // Projection window — D5 audit fix: value a FIXED number of controlled
  // seasons (yoc) from EXPECTED ARRIVAL (maturity for prospects, today for
  // established players) instead of the old fixed CALENDAR window
  // (age+yoc, floored at PEAK_END+2). The old window silently shrank a young
  // prospect's counted seasons — a 21-year-old kept only 2 post-arrival years
  // vs 6 at age 24 — grading identical 5-WAA-peak talent FV 52 at 21 vs 64 at
  // 24. Age now prices in ONLY through the time discount (deliberate) and the
  // separately-priced risk factor, never through a vanishing window.
  //
  // MAX_CAREER_AGE=34 was revisited (per D5) and deliberately KEPT as the clip
  // for established veterans: it encodes finite career length (a 32-year-old
  // does not have 6 full seasons left), and removing it would flatter old
  // players — the opposite of the interim-aging directive. It can never clip a
  // prospect's window (arrival ≤ ~25, so arrival + 6 ≤ 31 < 34).
  const isDevelopingProspect = hasPotential && gap > 0;
  const startAge = isDevelopingProspect ? Math.max(age, p.MATURITY_AGE) : age;
  const endAgeExcl = Math.min(startAge + yoc, p.MAX_CAREER_AGE);
  const projectionYears = Math.max(1, endAgeExcl - age);
  let peakProjectedWAA = -Infinity;
  let peakProjectedAsWAA = -Infinity;   // display track (see the parallel WAA block above)
  const yearByYear = [];

  // Build year-by-year projection (for the development curve chart)
  for (let y = 0; y < projectionYears; y++) {
    const futureAge = age + y;
    let yearWAA, yearAsWAA;

    if (hasPotential && futureAge < p.MATURITY_AGE && gap > 0) {
      const gf = getGapFactor(futureAge, p);
      yearWAA = currentWAA + (expectedPeakWAA - currentWAA) * (gf / p.GAP_MAX);
      yearAsWAA = currentAsWAA + (expectedPeakAsWAA - currentAsWAA) * (gf / p.GAP_MAX);
    } else if (futureAge <= p.PEAK_END) {
      yearWAA = expectedPeakWAA;
      yearAsWAA = expectedPeakAsWAA;
    } else {
      yearWAA = applyAging(expectedPeakWAA, futureAge, p);
      yearAsWAA = applyAging(expectedPeakAsWAA, futureAge, p);
    }

    const discountFactor = Math.pow(1 - p.DISCOUNT_RATE, y);
    peakProjectedWAA = Math.max(peakProjectedWAA, yearWAA);
    peakProjectedAsWAA = Math.max(peakProjectedAsWAA, yearAsWAA);

    yearByYear.push({
      age: futureAge,
      rawWAA: Math.round(yearWAA * 100) / 100,
      // display-WAA basis of the same year (rawWAA is the internal WAR/market
      // track and must stay — marketValue.js consumes it). Charts labeled WAA
      // must plot THIS, never rawWAA: the two differ by the role's market
      // replacement offset (~1.65 hitters / 2.5 SP), which made the model line
      // sit a constant offset above the measured overlay on the dev chart.
      waa: Math.round(yearAsWAA * 100) / 100,
      discountedWAA: Math.round((yearWAA * discountFactor) * 100) / 100,
    });
  }

  if (peakProjectedWAA === -Infinity) peakProjectedWAA = 0;
  if (peakProjectedAsWAA === -Infinity) peakProjectedAsWAA = 0;

  // ---- FUTURE VALUE CALCULATION ----
  // Two different approaches:
  //
  // PROSPECTS (hasPotential & gap > 0):
  //   FV = expectedPeakWAA × productive years (from maturity through decline)
  //   Discounted for time-to-reach-peak and risk.
  //   We DON'T count the negative development years — a 17-year-old in Rookie ball
  //   shouldn't be penalized for not being MLB-ready. What matters is what they'll
  //   produce once they arrive.
  //
  // ESTABLISHED PLAYERS (no potential data, age 24+):
  //   FV = sum of projected WAA from current age through career end.
  //   They are what they are — no development upside to factor in.

  let totalProjectedWAA = 0;

  if (isDevelopingProspect) {
    // Prospect valuation: count a FIXED yoc seasons from arrival (startAge,
    // computed above with the projection window) — the window no longer
    // shrinks with youth (D5).
    for (let y = 0; y < projectionYears; y++) {
      const futureAge = age + y;
      if (futureAge < startAge) continue; // skip development years

      const yearWAA = futureAge <= p.PEAK_END
        ? expectedPeakWAA
        : applyAging(expectedPeakWAA, futureAge, p);

      // Discount from TODAY (not from startAge), so more distant peak = lower present value
      const discountFactor = Math.pow(1 - p.DISCOUNT_RATE, y);
      totalProjectedWAA += yearWAA * discountFactor;
    }
  } else {
    // Established player: sum all projected years
    for (const entry of yearByYear) {
      totalProjectedWAA += entry.discountedWAA;
    }
  }

  const futureValue = totalProjectedWAA;
  const fvScale = rawFVtoScale(futureValue);

  // % to Peak: how close is their current WAA to their potential?
  // -8 current / 5 potential → they're nowhere near peak
  // 4 current / 5 potential → they're 80% there
  // For established players (no potential data), they ARE at their peak → 100%
  // For players with negative potential, cap at 0%
  let pctToPeak;
  if (!hasPotential || potentialWAA <= 0) {
    pctToPeak = 100; // established or no upside
  } else if (currentWAA <= 0) {
    // Negative current, positive potential — use gap factor progress
    // This gives a meaningful 0-95% based on age/development
    pctToPeak = Math.round(getGapFactor(age, p) / p.GAP_MAX * 100);
  } else {
    // Both positive — simple ratio
    pctToPeak = Math.min(100, Math.round((currentWAA / potentialWAA) * 100));
  }

  // Years til peak: how many years until they hit maturity (or 0 if already there)
  const yearsTilPeak = Math.max(0, p.MATURITY_AGE - age);

  return {
    futureValue: Math.round(futureValue * 100) / 100,
    fvScale,
    currentWAA: Math.round(currentWAA * 100) / 100,
    potentialWAA: Math.round(potentialWAA * 100) / 100,
    hasPotential,
    expectedPeakWAA: Math.round(expectedPeakWAA * 100) / 100,
    peakProjectedWAA: Math.round(peakProjectedWAA * 100) / 100,
    pctToPeak,
    yearsTilPeak,
    projectionYears,
    totalProjectedWAA: Math.round(totalProjectedWAA * 100) / 100,
    yearByYear,
    // Role replacement offsets baked into the WAR values above. offsetUsed belongs
    // to currentWAA, potentialOffsetUsed to potentialWAA — they DIFFER whenever the
    // best current role and the best peak role differ (common for young arms).
    offsetUsed: waaVals.offsetUsed,
    potentialOffsetUsed: waaVals.potentialOffsetUsed,
    currentRole: waaVals.currentRole,
    potentialRole: waaVals.potentialRole,
    // DISPLAY BASIS = WAA (vs average). Boards must read these, never subtract an
    // offset themselves — a single offset cannot convert a two-role player.
    displayWAA: {
      current: Math.round(currentAsWAA * 100) / 100,
      potential: Math.round(potentialAsWAA * 100) / 100,
      expectedPeak: Math.round(expectedPeakAsWAA * 100) / 100,
      peakProjected: Math.round(peakProjectedAsWAA * 100) / 100,
    },
  };
}

// ============================================================
// DEV ANALYSIS HELPERS — for the impact table
// ============================================================

/**
 * Median current WAA by age bucket (from data analysis).
 * Used in the Dev Analysis impact table to show realistic "curr:" values.
 */
export const MEDIAN_CURRENT_WAA_BY_AGE = {
  16: -9.4, 17: -9.3, 18: -9.0, 19: -7.7, 20: -7.5,
  21: -5.6, 22: -4.9, 23: -3.8, 24: -3.2, 25: -2.8,
  26: -2.8, 27: -3.2, 28: -3.7, 29: -4.5, 30: -5.0,
};

/**
 * Compute FV impact for a given age, potential WAA, and development percentile.
 * Used by the Dev Analysis impact table.
 *
 * @param {number} age - Player age
 * @param {number} potentialWAA - Assumed potential WAA
 * @param {number} percentile - Development percentile (0-100)
 * @param {Object} [params] - Override model parameters
 * @returns {Object} { futureValue, fvScale, currentWAA }
 */
export function computeImpact(age, potentialWAA, percentile, params = {}) {
  const p = { ...FV_DEFAULTS, ...params };

  // Use median current WAA for this age
  const currentWAA = MEDIAN_CURRENT_WAA_BY_AGE[age] || MEDIAN_CURRENT_WAA_BY_AGE[30];

  // Risk factor at specified percentile
  const risk = getRiskFactor(percentile, p);

  // For the impact table, we have two regimes:
  //
  // DEVELOPING (age < MATURITY_AGE): Player has a gap between current and potential.
  //   The expected peak WAA is currentWAA + gap * GAP_MAX * risk.
  //   We only count WAA from maturity onward (skip the negative development years).
  //
  // MATURE (age >= MATURITY_AGE): Player has REACHED their potential.
  //   Their peak WAA IS the potentialWAA (the "what-if" scenario).
  //   We project potentialWAA forward through the aging curve.
  //   This answers "what is a 3.0 WAA player worth at age 25/26/28/30?"

  const isDeveloping = age < p.MATURITY_AGE;
  const gap = potentialWAA - currentWAA;

  let peakWAA;
  if (isDeveloping && gap > 0) {
    // Young prospect: expected peak based on gap closing with risk
    peakWAA = currentWAA + gap * p.GAP_MAX * risk;
  } else {
    // Mature player: they've reached potential, so peak = potentialWAA
    peakWAA = potentialWAA;
  }

  // D5 audit fix (same as calculateFutureValue): fixed number of controlled
  // seasons from expected arrival, not a calendar window that shrinks with youth.
  const startAge = isDeveloping ? Math.max(age, p.MATURITY_AGE) : age;
  const endAgeExcl = Math.min(startAge + p.DEFAULT_YEARS_OF_CONTROL, p.MAX_CAREER_AGE);
  const projectionYears = Math.max(1, endAgeExcl - age);
  let totalProjectedWAA = 0;

  if (isDeveloping) {
    // Prospect: only count from arrival onward (skip development years)
    for (let y = 0; y < projectionYears; y++) {
      const futureAge = age + y;
      if (futureAge < startAge) continue;
      const yearWAA = futureAge <= p.PEAK_END
        ? peakWAA
        : applyAging(peakWAA, futureAge, p);
      totalProjectedWAA += yearWAA * Math.pow(1 - p.DISCOUNT_RATE, y);
    }
  } else {
    // Mature: project potentialWAA through aging curve from current age
    for (let y = 0; y < projectionYears; y++) {
      const futureAge = age + y;
      const yearWAA = futureAge <= p.PEAK_END
        ? peakWAA
        : applyAging(peakWAA, futureAge, p);
      totalProjectedWAA += yearWAA * Math.pow(1 - p.DISCOUNT_RATE, y);
    }
  }

  return {
    futureValue: Math.round(totalProjectedWAA * 100) / 100,
    fvScale: rawFVtoScale(totalProjectedWAA),
    currentWAA: Math.round(currentWAA * 100) / 100,
  };
}

export { getPlayerWAAValues, rawFVtoScale, FV_ANCHORS };
