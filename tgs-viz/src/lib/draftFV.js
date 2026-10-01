/**
 * TGS Draft FV Calculator
 *
 * Age-relative prospect valuation system for draft decisions.
 *
 * Unlike the existing FV (which measures cumulative projected WAA over a career),
 * Draft FV answers the draft question:
 *   1. Can this player compete against his age group RIGHT NOW?
 *   2. How high is his ceiling by maturity (~25)?
 *
 * Formula:
 *   Draft FV = (agePercentile × 0.30 + ceilingScore × 0.60 + peakScore × 0.10)
 *              × redFlagModifiers
 *
 * The blend is monotone in its three inputs; only the modifiers below can reorder two
 * prospects, and they are deliberately small so they decide near-ties rather than
 * overturn real gaps. Healthy durability tiers score alike on purpose: a 5% step
 * between Normal and Durable used to outrank genuine differences in the inputs.
 *
 * Key inputs:
 *   - Hitters: 0.7·Off Runs + 0.3·Def Runs (current; 70/30 bat-glove per user), MAX WAA P (ceiling)
 *   - Pitchers: WAA wtd (current), WAP (ceiling)
 *   - _potentialWAA (projected peak): Proj Potential, stamped upstream by
 *     usePlayersWithFV: from the ML model when the row has it (his WAA today + the ML
 *     median gain), else his WAA today + the DEV cell gain or the measured curve. Same
 *     units and anchors as the ceiling, so the two sit on one scale.
 *   - Prone column: Wrecked = undraftable, Fragile = 0.75; Normal/Durable/Iron Man = 1.0
 *   - WrkEthic column: H +1.5%, N even, L -1.5%
 *   - Int column: same, so H/H carries +3.0% and L/L carries -3.0%
 *
 * Age percentile is computed against the FULL league population for statistical
 * stability (~500 players per age bucket vs ~30-130 in draft pool alone).
 */

// ============================================================
// TUNABLE DEFAULTS
// ============================================================

import { replacementOffset } from './leagueCalib.js';

export const DRAFT_FV_DEFAULTS = {
  // Weighting: how far he leads his age peers, how high he can get, and how much of
  // that he is realistically expected to reach. Must sum to 1.
  CURRENT_WEIGHT: 0.30,
  CEILING_WEIGHT: 0.60,
  PEAK_WEIGHT:    0.10,

  // Ceiling normalization — unified scale: WAA is WAA. More WAA = better player,
  // no clamping at the top so elite outliers keep getting credit.
  CEILING_FLOOR:   -3.0,   // anchors the bottom of the scale (floor for below-replacement)
  CEILING_ANCHOR:   5.0,   // anchors raw WAA of 5.0 = score 100 (linear above)
};

// ============================================================
// DURABILITY MODIFIER
// ============================================================

// Only a RED FLAG may score below 1.0. Normal/Durable/Iron Man are all "healthy" and
// score identically: splitting them let a 5% step outrank real gaps in the inputs, so a
// Normal prospect ahead on both age percentile and ceiling could sit below a Durable one
// behind on both. Fragile and Wrecked are real risk and are allowed to break that order.
const DURABILITY_MAP = {
  'Wrecked':  0,      // undraftable (short-circuited before scoring)
  // Draft policy, not an estimate: a fragile prospect has to be clearly better than the
  // field before he is worth taking, so he must clear the board by ~25% to rank level.
  // Injury proneness is real and externally tracked; this number sets the premium
  // demanded for carrying that risk, which is a preference and not something a fit
  // could discover.
  'Fragile':  0.75,
  'Normal':   1.0,
  'Durable':  1.0,
  'Iron Man': 1.0,
};

/**
 * Get the growth multiplier based on injury proneness.
 * @param {string} proneValue - "Wrecked", "Fragile", "Normal", "Durable", "Iron Man"
 * @returns {number} Multiplier (0 to 1.0); only Fragile/Wrecked are below 1
 */
export function getDurabilityModifier(proneValue) {
  if (!proneValue || typeof proneValue !== 'string') return 1.0; // unknown is not a red flag
  return DURABILITY_MAP[proneValue] ?? 1.0;
}

// ============================================================
// WORK ETHIC / INTELLIGENCE MODIFIERS
// ============================================================

// Symmetric personality step, applied once for work ethic and once for intelligence,
// so a prospect high in both carries +3.0% and one low in both carries -3.0%. Sized
// deliberately small: these break near-ties between otherwise similar prospects and
// must not overturn a real gap in age percentile or ceiling. A draft preference, set
// by the user 2026-08-11 — not an estimate of a quantity a fit could recover.
const PERSONALITY_STEP = 0.015;

const personalityMod = (v) =>
  v === 'H' ? 1 + PERSONALITY_STEP : v === 'L' ? 1 - PERSONALITY_STEP : 1.0;

/**
 * Work ethic: high is a boost, low is the same size penalty.
 * @param {string} weValue - OOTP WrkEthic: "L", "N" or "H"
 * @returns {number} 1.015 / 1.0 / 0.985
 */
export function getWorkEthicModifier(weValue) {
  return personalityMod(weValue);
}

/**
 * Intelligence: same treatment as work ethic.
 * @param {string} intValue - OOTP Int: "L", "N" or "H"
 * @returns {number} 1.015 / 1.0 / 0.985
 */
export function getIntelligenceModifier(intValue) {
  return personalityMod(intValue);
}

// ============================================================
// TOOL RATING PENALTIES
// ============================================================

// --- Pitcher: pitch repertoire ---
const PITCH_COLS = ['FB', 'CH', 'CB', 'SL', 'SI', 'SP', 'CT', 'FO', 'CC', 'SC', 'KC', 'KN'];

/**
 * Pitcher penalty: weak changeup on a 3-pitch arm.
 * Knuckleballers and 4+ pitch guys are exempt.
 */
export function getPitchPenalty(player) {
  let pitchCount = 0;
  let hasKN = false;
  let chIsWeak = false;

  for (const col of PITCH_COLS) {
    const raw = player[col];
    if (raw === null || raw === undefined || raw === '-' || raw === '') continue;
    const val = parseFloat(raw);
    if (isNaN(val) || val <= 0) continue;

    pitchCount++;
    if (col === 'KN') hasKN = true;
    if (col === 'CH' && val <= 20) chIsWeak = true;
  }

  if (hasKN) return 1.0;
  if (pitchCount >= 4) return 1.0;
  if (chIsWeak) return 0.95;
  return 1.0;
}

// --- Hitter: key offensive tool weakness ---
const HITTER_TOOL_COLS = ['POW vR', 'EYE vR', 'K vR', 'BA vR'];

/**
 * Hitter penalty: 5% age percentile penalty if any core hitting tool
 * (power, eye, avoid K, contact) is rated 20 or below.
 * 20 is the floor — you don't know how bad it really is.
 */
export function getHitterToolPenalty(player) {
  for (const col of HITTER_TOOL_COLS) {
    const raw = player[col];
    if (raw === null || raw === undefined) continue;
    const val = parseFloat(raw);
    if (!isNaN(val) && val <= 20) return 0.95;
  }
  return 1.0;
}

// --- Pitcher: core pitching tool weakness ---
const PITCHER_TOOL_COLS = ['CON vR', 'STU vR', 'HRR vR'];

/**
 * Pitcher tool penalty: 5% age percentile penalty if control, stuff,
 * or HR rate is rated 20 or below.
 */
export function getPitcherToolPenalty(player) {
  for (const col of PITCHER_TOOL_COLS) {
    const raw = player[col];
    if (raw === null || raw === undefined) continue;
    const val = parseFloat(raw);
    if (!isNaN(val) && val <= 20) return 0.95;
  }
  return 1.0;
}

// ============================================================
// AGE GROUP BUILDER
// ============================================================

/**
 * Pre-compute sorted metric arrays for each integer age.
 * Used for efficient percentile lookups.
 *
 * @param {Array} allPlayers - Full league population (e.g., data.hitters)
 * @param {string|Function} metricKeyOrFn - Column name or function(player) => number
 * @returns {Object} Map of age -> sorted number[] (ascending)
 */
export function buildAgeGroups(allPlayers, metricKeyOrFn) {
  const getValue = typeof metricKeyOrFn === 'function'
    ? metricKeyOrFn
    : (player) => parseFloat(player[metricKeyOrFn]);

  const groups = {};

  for (const player of allPlayers) {
    const age = Math.floor(parseFloat(player.Age));
    if (isNaN(age) || age <= 0) continue;

    const val = getValue(player);
    if (isNaN(val)) continue;

    if (!groups[age]) groups[age] = [];
    groups[age].push(val);
  }

  // Sort each age group ascending
  for (const age of Object.keys(groups)) {
    groups[age].sort((a, b) => a - b);
  }

  return groups;
}

// ============================================================
// AGE PERCENTILE
// ============================================================

/**
 * Compute the percentile rank of a value within its age group.
 * Higher is better for both wOBA (hitters) and WAA (pitchers).
 *
 * @param {number} value - Player's metric value
 * @param {number} age - Player's integer age
 * @param {Object} ageGroups - From buildAgeGroups()
 * @returns {number} Percentile 0-100
 */
export function getAgePercentile(value, age, ageGroups) {
  const sorted = ageGroups[age];
  if (!sorted || sorted.length <= 1) return 50; // no meaningful comparison

  // Count how many values this player is >= (rank from bottom)
  let rank = 0;
  for (let i = 0; i < sorted.length; i++) {
    if (sorted[i] <= value) rank = i + 1;
    else break;
  }

  return (rank / sorted.length) * 100;
}

// ============================================================
// CEILING NORMALIZATION
// ============================================================

/**
 * Normalize a ceiling metric to a comparable 0-100+ scale.
 * Linear map: floor → 0, anchor → 100. Above the anchor scores >100 so elite
 * outliers (e.g., WAP 4.2 vs 5.0) keep getting differentiated credit. Below
 * floor is clamped to 0 (you can't be MORE useless than the floor).
 *
 * @param {number} value - Raw ceiling (MAX WAA P or WAP)
 * @param {number} floor - Raw value that maps to 0
 * @param {number} anchor - Raw value that maps to 100 (NOT clamped above)
 * @returns {number} Score (0 at floor, 100 at anchor, can exceed 100)
 */
function normalizeCeiling(value, floor, anchor) {
  if (isNaN(value)) return 0;
  const clampedLow = Math.max(floor, value);
  return ((clampedLow - floor) / (anchor - floor)) * 100;
}

// ============================================================
// DRAFT FV SCALE — 0-100 raw to 20-80 scouting scale
// ============================================================

const DRAFT_FV_ANCHORS = [
  { raw: 0,   fv: 20 },
  { raw: 15,  fv: 30 },
  { raw: 30,  fv: 35 },
  { raw: 40,  fv: 40 },
  { raw: 50,  fv: 45 },
  { raw: 60,  fv: 50 },
  { raw: 70,  fv: 55 },
  { raw: 78,  fv: 60 },
  { raw: 85,  fv: 65 },
  { raw: 92,  fv: 70 },
  { raw: 100, fv: 80 },
];

/**
 * Convert raw Draft FV score (0-100) to 20-80 scouting scale.
 * @param {number} rawScore
 * @returns {number} FV on 20-80 scale
 */
export function rawScoreToDraftFVScale(rawScore) {
  if (rawScore <= DRAFT_FV_ANCHORS[0].raw) return DRAFT_FV_ANCHORS[0].fv;

  const last = DRAFT_FV_ANCHORS[DRAFT_FV_ANCHORS.length - 1];
  if (rawScore >= last.raw) return last.fv;

  for (let i = 0; i < DRAFT_FV_ANCHORS.length - 1; i++) {
    const lo = DRAFT_FV_ANCHORS[i];
    const hi = DRAFT_FV_ANCHORS[i + 1];
    if (rawScore >= lo.raw && rawScore < hi.raw) {
      const t = (rawScore - lo.raw) / (hi.raw - lo.raw);
      return Math.round(lo.fv + t * (hi.fv - lo.fv));
    }
  }

  return 40; // fallback
}

// ============================================================
// MAIN CALCULATOR
// ============================================================

/**
 * Calculate Draft FV for a single player.
 *
 * @param {Object} player - Player data object
 * @param {Object} ageGroups - Pre-built from buildAgeGroups (full league population)
 * @param {'hitter'|'pitcher'} playerType
 * @param {Object} [params] - Override DRAFT_FV_DEFAULTS
 * @returns {Object} Draft FV breakdown
 */
export function calculateDraftFV(player, ageGroups, playerType, params = {}) {
  const p = { ...DRAFT_FV_DEFAULTS, ...params };
  const age = Math.floor(parseFloat(player.Age));
  const proneValue = player.Prone || null;
  const isWrecked = proneValue === 'Wrecked';

  // Wrecked is NOT short-circuited. It used to return a hard draftCeiling/
  // draftCeilingWAA of 0, which is fine on a draft board (you do not spend a pick on him,
  // and the board hides him anyway) but wrong everywhere else: HittersPage and
  // PitchersPage run this same hook, so an established player or free agent showed a
  // fabricated 0 ceiling. Henderson Macias — 2.42 WAA, 4.07 WAR, elite CF glove and legs
  // — read as a 0-ceiling player purely because of the flag.
  // Nothing special is needed: DURABILITY_MAP maps Wrecked to 0, so the draft SCORE still
  // collapses to 0 on its own, while the ceiling stays honest and `wrecked` keeps driving
  // the board's own hide filter.

  // ---- Extract metrics based on player type ----
  // CEILING IS WINS, PLAIN. It answers one question: how many wins above average does
  // this player add if he reaches his potential? That is the sheet's own MAX WAA P
  // (hitters) / WAP / WAP RP (pitchers), used as-is.
  //
  // It used to carry each role's replacement offset (hitter 1.91, SP 2.50, RP 0.31 in
  // BLM) so roles shared a "freely available talent" currency. That made the number the
  // board DISPLAYED differ from the number it SCORED: three BLM prospects all showing a
  // 0.6 ceiling scored 65.3 (hitter), 76.5 (SP) and 50.1 (RP) purely by role. The
  // normalization anchors below were always written in WAA, so this restores their
  // intent. Role value belongs in the dollar layer, not in "how good can he get".
  const _lg = player._appLeague;   // stamped by usePlayerData (raw 'League' is a numeric id)
  const _spOff = replacementOffset(_lg, 'sp');
  const _rpOff = replacementOffset(_lg, 'rp');
  let currentPerf, ceiling;
  // Kept at 0 so draftCeiling and draftCeilingWAA are the same number: the board shows
  // exactly what the score used.
  const ceilingOffset = 0;
  let ceilingRole = null;

  if (playerType === 'hitter') {
    // 0.7·Off Runs + 0.3·Def Runs (matches usePlayersWithDraftFV's age-group
    // metric — the two must stay identical). Bare wOBA ignored the delivered
    // glove (Otoo/young-C case); full run value overweighted it — the 70/30
    // bat-glove lean is the user's preference (2026-09-04), current leg only.
    const _o = parseFloat(player['Off Runs']);
    const _d = parseFloat(player['Def Runs']);
    currentPerf = (Number.isFinite(_o) && Number.isFinite(_d)) ? 0.7 * _o + 0.3 * _d : NaN;
    ceiling = parseFloat(player['MAX WAA P']);
    // Mature players (no potential data): current best WAA IS their ceiling
    if (isNaN(ceiling)) {
      ceiling = parseFloat(player['Max WAA wtd']);
    }
    if (!isNaN(ceiling)) ceilingRole = 'hitter';
  } else {
    // Pitchers: best of SP or RP for both current and ceiling, in WAR
    const spCurrent = parseFloat(player['WAA wtd']);
    const rpCurrent = parseFloat(player['WAA wtd RP']);
    currentPerf = Math.max(isNaN(spCurrent) ? -Infinity : spCurrent + _spOff,
                           isNaN(rpCurrent) ? -Infinity : rpCurrent + _rpOff);
    if (!isFinite(currentPerf)) currentPerf = NaN;

    // Role is an ELIGIBILITY test, not a value comparison. The engine's Starter flag
    // (engine/pitchers.py, the sheet's own rule) is enough starter-quality pitches plus
    // stamina; a non-qualifier gets no starter projection at all and WAP ships blank.
    //
    // Picking the higher of WAP / WAP RP instead put 98% of qualified starters in the
    // bullpen — 319 of 325 BLM prospects and 415 of 442 in TGS have a higher RELIEF
    // ceiling on paper, because a developing arm gets unloaded the third time through
    // the order. Scoring a starting prospect on his bullpen ceiling buries him. Same
    // reasoning orgBuilder.js:64 already applies to minor-league rotations.
    // Eligibility GATES which lines are available; among the ones he can actually
    // fill, his ceiling is simply the best of them. A pitcher who adds more wins in
    // relief is a reliever. Note the two rules agree exactly at the top of the board —
    // they differ only on arms projecting BELOW average as starters, where relief
    // "wins" purely because it is 70 innings of a bad pitcher instead of 200.
    const isStarter = player['Starter'] === true ||
      String(player['Starter']).toUpperCase() === 'TRUE';
    const spCeiling = parseFloat(player['WAP']);
    const rpCeiling = parseFloat(player['WAP RP']);
    const spOk = isStarter && !isNaN(spCeiling);

    if (spOk && !isNaN(rpCeiling)) {
      const useSP = spCeiling >= rpCeiling;
      ceiling = useSP ? spCeiling : rpCeiling;
      ceilingRole = useSP ? 'sp' : 'rp';
    } else if (spOk) {
      ceiling = spCeiling; ceilingRole = 'sp';
    } else if (!isNaN(rpCeiling)) {
      ceiling = rpCeiling; ceilingRole = 'rp';
    } else if (!isNaN(spCeiling)) {
      ceiling = spCeiling; ceilingRole = 'sp';
    } else {
      // No potential data — his current best in the role he can actually fill
      const spCur = isStarter && !isNaN(spCurrent) ? spCurrent : -Infinity;
      const rpCur = isNaN(rpCurrent) ? -Infinity : rpCurrent;
      ceiling = Math.max(spCur, rpCur);
      if (!isFinite(ceiling)) ceiling = NaN;
      ceilingRole = spCur >= rpCur ? 'sp' : 'rp';
    }
  }

  // ---- Age-relative percentile ----
  // B11 (audit): an UNPARSEABLE/MISSING current-performance value (or age) is
  // "no information", not "worst in class" — default to the 50th percentile,
  // matching getAgePercentile's own no-comparison fallback. The old 0th-
  // percentile default cratered every prospect whose current-perf column was
  // blank, purely on data plumbing.
  let agePercentile = (!isNaN(currentPerf) && !isNaN(age) && age > 0)
    ? getAgePercentile(currentPerf, age, ageGroups)
    : 50;

  // ---- Tool rating penalties (applied to age percentile) ----
  let toolPenalty;
  if (playerType === 'pitcher') {
    const pitchPen = getPitchPenalty(player);
    const toolPen = getPitcherToolPenalty(player);
    toolPenalty = Math.min(pitchPen, toolPen); // worst penalty wins, don't stack
  } else {
    toolPenalty = getHitterToolPenalty(player);
  }
  agePercentile *= toolPenalty;

  // ---- Ceiling score (unified WAA scale, no upper clamp) ----
  const ceilingScore = normalizeCeiling(ceiling, p.CEILING_FLOOR, p.CEILING_ANCHOR);

  // ---- Projected peak (the realistic ceiling) ----
  // _potentialWAA is stamped by usePlayersWithFV upstream: Proj Potential (the ML
  // model's peak when present, else the DEV cell or the measured curve). Same units (WAA) and the same anchors, so
  // it lands on one scale with ceilingScore. Ceiling is the payoff, this is the payoff
  // discounted by how much of it he is actually expected to reach.
  const peakWAA = parseFloat(player._potentialWAA);
  const hasPeak = !isNaN(peakWAA);
  const peakScore = hasPeak
    ? normalizeCeiling(peakWAA, p.CEILING_FLOOR, p.CEILING_ANCHOR)
    : null;
  // Missing peak (no FV enrichment on this row) folds its weight back into ceiling
  // rather than scoring zero, which would crater an otherwise fine prospect.
  const ceilW = hasPeak ? p.CEILING_WEIGHT : p.CEILING_WEIGHT + p.PEAK_WEIGHT;
  const peakW = hasPeak ? p.PEAK_WEIGHT : 0;

  // ---- Red-flag modifiers ----
  // The board ranks on two things: how far a prospect leads his age peers, and how high
  // he projects. Among prospects with no red flag the score is strictly monotone in
  // those two — ahead on both can never rank lower. ONLY a red flag (Fragile/Wrecked,
  // low work ethic, low intelligence) may break that order, which is the whole point of
  // a flag. Every healthy durability tier scores 1.0, so Normal vs Durable cannot
  // reorder anyone. Before 2026-08-11 these multiplied every score and produced 146/504
  // (BLM hitters/pitchers) and 270/1007 (TGS) pairs that were ahead on both and ranked
  // below anyway.
  const durabilityMod = getDurabilityModifier(proneValue);
  const weMod = getWorkEthicModifier(player.WrkEthic);
  const intMod = getIntelligenceModifier(player.Int);

  // ---- Combine ----
  const rawScore = (agePercentile * p.CURRENT_WEIGHT
                    + ceilingScore * ceilW
                    + (hasPeak ? peakScore * peakW : 0))
    * durabilityMod * weMod * intMod;

  const draftFV = rawScoreToDraftFVScale(rawScore);

  return {
    draftFV,
    draftRawFV: Math.round(rawScore * 100) / 100,
    agePercentile: Math.round(agePercentile * 10) / 10,
    ceilingScore: Math.round(ceilingScore * 10) / 10,
    peakScore: peakScore === null ? null : Math.round(peakScore * 10) / 10,
    // draftCeiling is WAR (what ceilingScore/draftFV are actually scored on, and what
    // the board's membership filter + above/below-zero sort tier key off — unchanged).
    draftCeiling: isNaN(ceiling) ? null : Math.round(ceiling * 100) / 100,
    // draftCeilingWAA is the SAME ceiling in the board's display currency.
    draftCeilingWAA: isNaN(ceiling) ? null : Math.round((ceiling - ceilingOffset) * 100) / 100,
    ceilingOffset,
    ceilingRole,
    durabilityMod,
    toolPenalty,
    proneValue: proneValue || 'Normal',
    highINT: player.Int === 'H',
    wrecked: isWrecked,   // still flags him; the draft board's hideWrecked filter reads this
    weBoost: player.WrkEthic === 'H',
  };
}
