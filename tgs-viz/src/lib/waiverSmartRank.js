/**
 * waiverSmartRank.js — ours' Smart Rank adjustments, ported for the Waiver
 * Claim page.
 *
 * Source: ootp-dashboard app/src/utils/futureValue.js `applySmartRank` and
 * app/src/utils/helpers.js `calcRawIntangibles`, with the tuning from
 * app/src/utils/constants.js `SMART_RANK_TUNING`.
 *
 * Only the two adjustments that read nothing but the player's own data fields
 * are ported:
 *   - Injury proneness: a penalty looked up from `Prone`.
 *   - Intangibles: a bonus from a 20-80 grade built from the personality
 *     letters (H / N / L), normalised over the league's own rows.
 * Ours' other two waiver toggles are not ported. "Future Value" runs ours'
 * hand-tuned FV curve, which the migration plan drops in favour of his
 * measured / ML development. "Org Positional Need" needs ours' strength
 * z-scores, which are a model, not a data field.
 *
 * The base the adjustments land on is HIS claim value, `vor` (WAA above org
 * replacement), not ours' WAR P. Both are in wins, so ours' win-valued deltas
 * add in the same unit.
 *
 * 🟡 Borrowed constants (ours' calibration, signed off in ours, not re-checked
 * against his WAA scale): RP_ADJUST_SCALE, PRONE_PENALTY_WAR, INT_BONUS_WAR,
 * and the intangible weights.
 */

import { getIntangible, getProne } from './accessors.js';

// ours' constants.js SMART_RANK_TUNING (subset), values verbatim.
export const SMART_RANK_TUNING = {
  // RP-role scale = IP_RP / IP_SP = 69.55 / 185.47 ≈ 0.375 (ours' calibration).
  RP_ADJUST_SCALE: 0.375,
  // Penalty in wins (a negative penalty is a bonus).
  PRONE_PENALTY_WAR: {
    'Iron Man': -0.5,
    'Durable': -0.3,
    'Normal': 0,
    'Fragile': 0.9,
    'Wrecked': 2.0,
  },
  // Wins per 10 grade points away from 50.
  INT_BONUS_WAR: 0.15,
};

// ours' helpers.js INT_WEIGHTS / INT_INVERTED, verbatim. His rows carry no
// adaptability ('ad') and the bridge maps no column to ours' 'fin', so those
// two weights drop out and the average renormalises over the keys present.
const INT_WEIGHTS = { lea: 0.15, loy: 0.10, ad: 0.05, fin: 0.10, we: 0.35, int: 0.25 };
const INT_INVERTED = new Set(['fin']);

function intangibleFieldScore(key, val) {
  if (!val || val === '-') return null;
  if (val === 'H') return INT_INVERTED.has(key) ? 4 : 17;
  if (val === 'L') return INT_INVERTED.has(key) ? 17 : 4;
  if (val === 'N') return 10;
  return null;
}

/** Weighted personality score before normalising (ours' calcRawIntangibles). */
export function rawIntangibles(p) {
  let wSum = 0;
  let wTotal = 0;
  for (const [k, w] of Object.entries(INT_WEIGHTS)) {
    const s = intangibleFieldScore(k, getIntangible(p, k));
    if (s != null) { wSum += s * w; wTotal += w; }
  }
  return wTotal === 0 ? null : wSum / wTotal;
}

/**
 * A grader over one league's rows: returns p => 20-80 grade (or null). The
 * grade is 50 + 10 z against the mean and spread of every row that has a
 * score, clamped to 20-80 — ours' Dashboard enrich step, unchanged.
 */
export function intangiblesGrader(rows = []) {
  const scores = rows.map(rawIntangibles).filter(v => v != null);
  let mean = 0;
  let sd = 1;
  if (scores.length > 0) {
    mean = scores.reduce((a, b) => a + b, 0) / scores.length;
    const variance = scores.map(v => (v - mean) ** 2).reduce((a, b) => a + b, 0) / scores.length;
    sd = Math.sqrt(variance) || 1;
  }
  return (p) => {
    const raw = rawIntangibles(p);
    return raw == null ? null : Math.round(Math.max(20, Math.min(80, 50 + 10 * (raw - mean) / sd)));
  };
}

/** Wins taken off for injury proneness (negative = a bonus). Unknown = 0. */
export function pronePenalty(p) {
  const prone = getProne(p);
  return prone ? (SMART_RANK_TUNING.PRONE_PENALTY_WAR[prone] ?? 0) : 0;
}

/** Wins added for a 20-80 intangibles grade. No grade = 0. */
export function intangiblesBonus(grade) {
  if (grade == null) return 0;
  return ((grade - 50) / 10) * SMART_RANK_TUNING.INT_BONUS_WAR;
}

/**
 * Smart score for one claim-board entry (from waivers.js evaluateClaim).
 * `toggles` = { injury, intangibles }. `grade` is the entry's intangibles
 * grade. Returns null when the entry has no claim value to adjust.
 * RP-role entries get the deltas scaled by RP_ADJUST_SCALE, as in ours.
 */
export function smartScore(entry, toggles = {}, grade = null) {
  if (entry == null || entry.vor == null) return null;
  const scale = entry.role === 'rp' ? SMART_RANK_TUNING.RP_ADJUST_SCALE : 1;
  let score = entry.vor;
  if (toggles.injury) score -= scale * pronePenalty(entry.player);
  if (toggles.intangibles) score += scale * intangiblesBonus(grade);
  return score;
}

/** Sort entries by smart score, best first; entries without one go last. Returns a new array. */
export function sortBySmart(entries, scoreOf) {
  return [...entries].sort((a, b) => (scoreOf(b) ?? -Infinity) - (scoreOf(a) ?? -Infinity));
}
