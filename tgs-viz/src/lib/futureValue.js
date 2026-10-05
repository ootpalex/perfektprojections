/**
 * TGS Future Value Calculator v2
 *
 * Research-backed model using actual WAA data from the TGS sheets.
 *
 * TWO REGIMES (2026-09-24):
 * - MEASURED PATH: when the caller passes { ageCurve } (the DEV league's
 *   true-ratings curve, ageCurve.js) the year-by-year path on that curve is
 *   the model, for every league and every age. Growth to 27 along the
 *   measured shape to current + the DEV cell gain ({ devGain }), or to the
 *   closable share of the listed gap without a cell, then the measured
 *   decline. See measuredPath and measuredTarget. The logistic gap factor,
 *   the risk factor, GAP_MAX and the interim aging schedule are not used on
 *   this path.
 * - ML PATH (2026-09-25): on the measured regime, a row that carries the ML
 *   path (Dev_MlD from devMl.js; user, 2026-09-24: "is there any way you can
 *   make a machine learning model to help with figuring out this dev
 *   stuff") takes its first five years from the ML model, see mlTrack.
 * - ASSUMED MODEL: without a curve the original model below runs unchanged.
 *
 * Key design decisions of the assumed model:
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
 * - Every row carries potential at every age (the old sheets cut it off after 23)
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
import { curveShape, GROWTH_END_AGE, PATH_END_AGE } from './ageCurve.js';

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
  let currentWAACols = [['Max WAA wtd', hOff, 'hitter'],
                          ['WAA wtd', spOff, 'sp'], ['WAA wtd RP', rpOff, 'rp']];
  let potentialWAACols = [['MAX WAA P', hOff, 'hitter'],
                          ['WAP', spOff, 'sp'], ['WAP RP', rpOff, 'rp']];
  // A pitcher's role is OOTP's listed POS (SP starts, RP/CL relieve), not whichever role
  // prices higher once its credit is added (user decision 2026-10-05, docs/PHASE1_AUDIT.md
  // D3). On SSB 2043 the listed role matched real usage for 75% of dual-role MLB arms (WAA
  // argmax 69%, WAR argmax 57%); WAR argmax made most of the draft class starters on the
  // 2.2-win credit gap alone. A row whose POS is not SP/RP/CL, or has no value for its listed
  // role, keeps the max over both roles.
  const pos = String(player.POS ?? '').trim().toUpperCase();
  const listedRole = pos === 'SP' ? 'sp' : (pos === 'RP' || pos === 'CL') ? 'rp' : null;
  const ownRole = (cols) => {
    if (!listedRole) return cols;
    const own = cols.filter(([col, , role]) => role === listedRole && !isNaN(parseFloat(player[col])));
    return own.length ? own : cols;
  };
  currentWAACols = ownRole(currentWAACols);
  potentialWAACols = ownRole(potentialWAACols);

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

  // No potential column on the row: potential = current (no development
  // upside). Today's files carry potential at every age, so this guards old
  // or partial files.
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
// MEASURED PATH: year-by-year WAA on the DEV curve
// ============================================================

/**
 * Year-by-year WAA path on the measured curve, from floor(age) to
 * PATH_END_AGE (40). One model for every league and every age.
 *
 * Growth (ages up to 27): the player moves from his current WAA to the
 * target along the measured growth shape G(a). The part of the shape still
 * ahead of him is rescaled to his own gap, so a 24-year-old spends the age
 * 24-27 share of the curve closing what is left:
 *   waa(a) = cur + (target - cur) * (G(a) - G(a0)) / (1 - G(a0))
 * measuredTarget never sets the target below current, so the path never
 * falls before 28. At 27 or older there is no growth step.
 *
 * Decline (ages 28+): each year adds the measured mean of the age he is
 * during that season, negative part only:
 *   waa(a) = waa(a-1) + min(0, mean(a-1))
 * Ages past the curve's last entry reuse its last mean.
 *
 * @param {Object} ageCurve - age_curve.json (curve[age].mean)
 * @param {number} age - current age (fractional allowed; floored for lookups)
 * @param {number} currentWAA - WAA today (any basis; the caller picks)
 * @param {number} targetWAA - where growth aims (measuredTarget; never below current)
 * @returns {Array<{age:number, waa:number}>|null} null when the curve is unusable
 */
export function measuredPath(ageCurve, age, currentWAA, targetWAA) {
  const shape = curveShape(ageCurve);
  if (!shape || !Number.isFinite(age) || !Number.isFinite(currentWAA)) return null;
  const a0 = Math.floor(age);
  const target = Number.isFinite(targetWAA) ? targetWAA : currentWAA;
  const g0 = shape.G(a0);
  const room = 1 - g0;
  const end = Math.max(PATH_END_AGE, a0);
  const out = [{ age: a0, waa: currentWAA }];
  let waa = currentWAA;
  for (let a = a0 + 1; a <= end; a++) {
    if (a <= GROWTH_END_AGE && room > 0) {
      waa = currentWAA + (target - currentWAA) * (shape.G(a) - g0) / room;
    } else {
      waa += Math.min(0, shape.mean(a - 1) ?? 0);
    }
    out.push({ age: a, waa });
  }
  return out;
}

/**
 * Growth target for the measured path, one track. The target is player
 * specific: his current WAA plus a measured gain.
 *
 * - With a DEV cell (cellGain finite): GAIN = the cell's median of (eventual
 *   peak WAA minus now-WAA) over DEV players with his age, Pot and growth.
 *   T = current + max(0, GAIN). No blend, no cap, no closure haircut.
 * - Without a cell (age 27+, thin cell, no Pot): T = current + closable(age)
 *   x max(0, listed - current), the curve's closure product on his listed
 *   gap.
 *
 * The target is never below current. A listed potential below current is
 * ignored: decline starts at 28 from the curve means (measuredPath).
 *
 * @returns {{target:number, source:'cell'|'listed'}}
 */
export function measuredTarget(ageCurve, age, currentWAA, listedWAA, cellGain) {
  const cur = currentWAA;
  if (Number.isFinite(cellGain)) return { target: cur + Math.max(0, cellGain), source: 'cell' };
  const shape = curveShape(ageCurve);
  const listed = Number.isFinite(listedWAA) ? listedWAA : cur;
  const gap = Math.max(0, listed - cur);
  const closable = shape ? shape.closable(age) : 1;
  return { target: cur + closable * gap, source: 'listed' };
}

/**
 * ML path, one track (2026-09-25). The ML model (backtest/ml, trained on the
 * DEV league) predicts his change in WAA 1..5 years out. Rule:
 *   years 1..5   cur + deltas[k-1] (the ML years)
 *   after year 5, up to 27: from the year-5 value toward the target along the
 *                measured growth shape G, rescaled to what is left of it:
 *                w5 + (target - w5) * (G(a) - G(a5)) / (1 - G(a5)); held at
 *                w5 when there is no target or it is not above w5
 *   28 on (and after year 5 for an older player): the DEV curve's per-age
 *                means, negative part only, exactly as measuredPath
 *   cap          when finite, no year goes above it (the display path of a
 *                player aged 26 or under is capped at his Proj Potential)
 *   noDip        (display path only, 2026-09-26) through age 27 each ML
 *                year is the higher of (a) the best of today and the ML
 *                years so far and (b) a steady climb from today to the
 *                target along the growth shape G (reaching it at 27): no
 *                dip, nothing below today before 28, no plateau-then-jump.
 *                The five ML years are five separate median models; for some
 *                players they disagreed and drew a 20-year-old rising,
 *                fading and going flat (user, 2026-09-26: "why would
 *                mckenna rise ease back then stay flat, like no player does
 *                that"). Held-out DEV rows aged 16-26 (time split, TGS
 *                basis), every row: median error at year 5 hitters 0.532
 *                raw -> 0.541, pitchers 0.224 -> 0.229 (within 2%), and the
 *                low bias smallest of the options tried (hitters -0.174 ->
 *                -0.125, pitchers -0.062 -> -0.026). The FV grade reads this
 *                path; the money path (means, expectedPath) keeps the raw
 *                ML changes.
 * Without noDip (the money path) an ML year may sit below today: some DEV
 * players did fall back before 28.
 *
 * @param {Object} shape - curveShape(ageCurve)
 * @param {number} a0 - floor(age)
 * @param {number} cur - WAA today (display basis)
 * @param {number[]} deltas - five ML changes (medians for display, means for money)
 * @param {number|null} target - where growth after year 5 aims (cur + ML gain q50), or null
 * @param {number|null} cap - top of the path, or null for no cap
 * @param {boolean} [noDip=false] - through 27, no ML year below today, an earlier ML year or the steady climb to the target
 * @returns {Array<{age:number, waa:number}>}
 */
export function mlTrack(shape, a0, cur, deltas, target, cap, noDip = false) {
  const end = Math.max(PATH_END_AGE, a0);
  const K = deltas.length;
  const capped = v => (Number.isFinite(cap) ? Math.min(v, cap) : v);
  const out = [{ age: a0, waa: cur }];
  let waa = cur;
  let w5 = cur;
  let best = 0;                 // noDip: the best change so far (today = 0)
  const a5 = a0 + K;
  for (let a = a0 + 1; a <= end; a++) {
    const k = a - a0;
    if (k <= K) {
      let dk = deltas[k - 1];
      if (noDip && a <= GROWTH_END_AGE) {
        best = Math.max(best, dk);
        dk = best;
        if (Number.isFinite(target) && target > cur) {
          const g0 = shape.G(a0);
          const share = g0 < 1 ? (shape.G(a) - g0) / (1 - g0) : 1;
          dk = Math.max(dk, (target - cur) * share);
        }
      }
      waa = capped(cur + dk);
      w5 = waa;
    } else if (a <= GROWTH_END_AGE) {
      const g5 = shape.G(a5);
      const room = 1 - g5;
      waa = Number.isFinite(target) && target > w5 && room > 0
        ? w5 + (target - w5) * (shape.G(a) - g5) / room
        : w5;
      waa = capped(waa);
    } else {
      waa += Math.min(0, shape.mean(a - 1) ?? 0);
    }
    out.push({ age: a, waa });
  }
  return out;
}

/**
 * Internal (WAR) track of a display track: display + the current role's
 * replacement offset, moving to the potential role's offset along the
 * growth shape from today to 27 (the same share measuredPath gives it, so a
 * reliever-now, starter-at-peak arm shifts roles on the same schedule).
 */
function warTrack(shape, a0, disp, oCur, oPot) {
  const g0 = shape.G(a0);
  const room = 1 - g0;
  return disp.map(x => {
    const s = room > 0 ? Math.min(1, Math.max(0, (shape.G(x.age) - g0) / room)) : 0;
    return { age: x.age, waa: x.waa + oCur + (oPot - oCur) * s };
  });
}

/** Five finite numbers, or null. */
function five(a) {
  return Array.isArray(a) && a.length === 5 && a.every(Number.isFinite) ? a : null;
}

/** Path value y years from now; the last entry past the end. */
function pathAt(path, y) {
  return path[Math.min(y, path.length - 1)].waa;
}

/** Index of the first maximum on the path (0 = today). */
function pathPeakIndex(path) {
  let best = 0;
  for (let i = 1; i < path.length; i++) if (path[i].waa > path[best].waa) best = i;
  return best;
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
 * @param {Object} [params] - Override model parameters (for Dev Analysis tuning).
 *        params.ageCurve (age_curve.json) switches on the measured path;
 *        params.devGain (the row's Dev_PeakGainP50, display WAA) is the
 *        cell gain its growth target adds to current when finite. Without
 *        ageCurve the assumed model runs as before.
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

  // Per-player risk factor based on age + gap size (assumed model only)
  const gap = potentialWAA - currentWAA;
  const riskFactor = getPlayerRisk(age, gap, hasPotential, p);

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
  // WAA inputs. Every display quantity mirrors an internal line, so the two
  // tracks cannot drift apart.
  const oCur = Number.isFinite(waaVals.offsetUsed) ? waaVals.offsetUsed : 0;
  const oPot = Number.isFinite(waaVals.potentialOffsetUsed) ? waaVals.potentialOffsetUsed : oCur;
  const currentAsWAA = currentWAA - oCur;
  const potentialAsWAA = potentialWAA - oPot;

  // ---- MEASURED PATH (params.ageCurve supplied) ----
  // The year-by-year path on the measured DEV curve replaces the logistic
  // gap factor and the PEAK_END / DECLINE_RATE / CLIFF aging on BOTH tracks.
  // Target (measuredTarget, display WAA): current + the DEV cell gain
  // (params.devGain) when the row has a cell, else current + the closable
  // share of his listed gap. ONE rule: the internal (WAR) target is the
  // display target plus the potential role's replacement offset, so the two
  // tracks stay in step exactly as the assumed model keeps them.
  // No riskFactor and no GAP_MAX on this path: the cell gain is already the
  // typical outcome for players like him, and the closure share is the
  // measured shortfall against a listed ceiling. A second haircut would
  // count the same risk twice.
  const devGain = Number.isFinite(p.devGain) ? p.devGain : null;
  const shape = p.ageCurve ? curveShape(p.ageCurve) : null;
  const measured = !!shape && Number.isFinite(age);
  let targetSource = null;
  let pathAs = null, path = null;
  // ML path (devMl.js, 2026-09-25): a row with the ML changes Dev_MlD runs
  // mlTrack instead. DISPLAY path (Year by year, card chart, Proj
  // Potential): years 1..5 = current + the ML medians; for ages 26 and
  // under Proj Potential = current + the ML gain q50 and the path is capped
  // at it. EXPECTED path (money, marketValue.agedWARPath): the same with the
  // ML means (Dev_MlDm) and no cap. Rows without the ML fields run exactly
  // as before.
  const mlD = measured ? five(player.Dev_MlD) : null;
  const mlDm = mlD ? (five(player.Dev_MlDm) || mlD) : null;
  const mlGainArr = Array.isArray(player.Dev_MlGain) ? player.Dev_MlGain : null;
  const mlGain = mlGainArr && Number.isFinite(mlGainArr[2]) ? mlGainArr[2] : devGain;
  let mlTarget = null;
  let expPathAs = null, expPath = null;
  if (mlD) {
    const a0 = Math.floor(age);
    mlTarget = a0 <= GROWTH_END_AGE - 1 && Number.isFinite(mlGain)
      ? currentAsWAA + Math.max(0, mlGain) : null;
    targetSource = 'ml';
    pathAs = mlTrack(shape, a0, currentAsWAA, mlD, mlTarget, mlTarget, true);
    path = warTrack(shape, a0, pathAs, oCur, oPot);
    expPathAs = mlTrack(shape, a0, currentAsWAA, mlDm, mlTarget, null);
    expPath = warTrack(shape, a0, expPathAs, oCur, oPot);
  } else if (measured) {
    const tAs = measuredTarget(p.ageCurve, age, currentAsWAA, potentialAsWAA, devGain);
    targetSource = tAs.source;
    pathAs = measuredPath(p.ageCurve, age, currentAsWAA, tAs.target);
    path = measuredPath(p.ageCurve, age, currentWAA, tAs.target + oPot);
  }

  // Expected peak WAA ("Proj Potential": what we think they'll actually reach).
  // Measured: the top of the path (today is index 0, so never below current).
  // Assumed (no curve): GAP_MAX x riskFactor with current floored at 0 so a
  // teenager's rookie-ball negative WAA doesn't drag his ceiling, and NO
  // growth credit from 25 on (league rule, user-stated). The 0-WAR floor in
  // baseForPeak is REPLACEMENT LEVEL for the role the peak is anchored on,
  // which in WAA is -potentialOffsetUsed.
  let expectedPeakWAA, expectedPeakAsWAA;
  let peakIdx = 0;
  if (measured) {
    peakIdx = pathPeakIndex(pathAs);
    expectedPeakAsWAA = pathAs[peakIdx].waa;
    expectedPeakWAA = path[pathPeakIndex(path)].waa;
    if (mlTarget !== null) {
      // ML, ages 26 and under: Proj Potential = current + the ML gain q50
      // (the display path is capped at it, so it may not reach it).
      expectedPeakAsWAA = mlTarget;
      expectedPeakWAA = mlTarget + oPot;
    }
  } else {
    const devCredit = age >= 25 ? 0 : 1;
    const baseForPeak = Math.max(currentWAA, 0);
    const developedPeak = baseForPeak + (potentialWAA - baseForPeak) * p.GAP_MAX * riskFactor;
    expectedPeakWAA = hasPotential && gap > 0
      ? currentWAA + (developedPeak - currentWAA) * devCredit
      : currentWAA;
    const baseAsWAA = baseForPeak === currentWAA ? currentAsWAA : -oPot;
    const developedPeakAsWAA = baseAsWAA + (potentialAsWAA - baseAsWAA) * p.GAP_MAX * riskFactor;
    expectedPeakAsWAA = hasPotential && gap > 0
      ? currentAsWAA + (developedPeakAsWAA - currentAsWAA) * devCredit
      : currentAsWAA;
  }

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
  const yearWAR = [];   // unrounded internal values, for the measured FV sum

  // Build year-by-year projection (for the development curve chart).
  // Measured: the path's own year values. Assumed: S-curve to maturity, flat
  // to PEAK_END, then the interim aging schedule.
  for (let y = 0; y < projectionYears; y++) {
    const futureAge = age + y;
    let yearWAA, yearAsWAA;

    if (measured) {
      yearWAA = pathAt(path, y);
      yearAsWAA = pathAt(pathAs, y);
    } else if (hasPotential && futureAge < p.MATURITY_AGE && gap > 0) {
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
    yearWAR.push(yearWAA);

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
  // ESTABLISHED PLAYERS (no gap left: potential at or below current, or no
  // potential column):
  //   FV = sum of projected WAA from current age through career end.
  //   They are what they are — no development upside to factor in.

  let totalProjectedWAA = 0;

  if (measured) {
    // Same structure as the assumed model below: a prospect's development
    // years (before startAge) are not counted, an established player counts
    // every year. The path's own year values replace the flat peak plus
    // aging. No riskFactor and no GAP_MAX here (see the measured path block).
    for (let y = 0; y < projectionYears; y++) {
      if (isDevelopingProspect && age + y < startAge) continue;
      totalProjectedWAA += yearWAR[y] * Math.pow(1 - p.DISCOUNT_RATE, y);
    }
  } else if (isDevelopingProspect) {
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
  if (measured) {
    // Same three cases against the path's own peak; the growth shape G
    // stands in for the logistic gap factor.
    if (expectedPeakAsWAA <= currentAsWAA || expectedPeakAsWAA <= 0) {
      pctToPeak = 100;
    } else if (currentAsWAA <= 0) {
      pctToPeak = Math.round(shape.G(age) * 100);
    } else {
      pctToPeak = Math.min(100, Math.round((currentAsWAA / expectedPeakAsWAA) * 100));
    }
  } else if (!hasPotential || potentialWAA <= 0) {
    pctToPeak = 100; // established or no upside
  } else if (currentWAA <= 0) {
    // Negative current, positive potential — use gap factor progress
    // This gives a meaningful 0-95% based on age/development
    pctToPeak = Math.round(getGapFactor(age, p) / p.GAP_MAX * 100);
  } else {
    // Both positive — simple ratio
    pctToPeak = Math.min(100, Math.round((currentWAA / potentialWAA) * 100));
  }

  // Years til peak. Measured: years from today to the top of the display
  // path. Assumed: years until maturity (or 0 if already there).
  const yearsTilPeak = measured ? peakIdx : Math.max(0, p.MATURITY_AGE - age);
  const peakAge = measured ? pathAs[peakIdx].age : null;

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
    // true when the measured DEV path produced everything above; false means
    // the assumed model (no curve supplied).
    measured,
    // What the display path grows toward: 'cell' (current + the DEV cell
    // gain), 'listed' (the closable share of his listed gap), 'ml' (the ML
    // path, devMl.js), null on the assumed model.
    targetSource,
    // Age of the top of the display path (null on the assumed model).
    peakAge,
    // The whole path from today to PATH_END_AGE: waa is the display track
    // (chart and the year-by-year columns), rawWAA the internal WAR track
    // (marketValue.js prices contracts and offers on it). null on the
    // assumed model.
    fullPath: pathAs
      ? pathAs.map((x, i) => ({
          age: x.age,
          waa: Math.round(x.waa * 100) / 100,
          rawWAA: Math.round(path[i].waa * 100) / 100,
        }))
      : null,
    // ML rows only (targetSource 'ml'): the EXPECTED path for money, the ML
    // means with no cap, same shape as fullPath. marketValue.agedWARPath
    // prices on it when present. Absent on every other row.
    ...(expPathAs ? {
      expectedPath: expPathAs.map((x, i) => ({
        age: x.age,
        waa: Math.round(x.waa * 100) / 100,
        rawWAA: Math.round(expPath[i].waa * 100) / 100,
      })),
    } : {}),
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
