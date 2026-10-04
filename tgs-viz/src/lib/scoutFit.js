// ============================================================================
// scoutFit.js — the Scout page's trade-fit score and position comparison,
// ported from ootp-dashboard ("ours": ScoutView.jsx, utils/strength.js
// calcOrgNeed, utils/futureValue.js applySmartRank, SMART_RANK_TUNING).
//
// What changed from ours (docs/phase4/views.md):
//   - Positional strength is his (lib/positionalStrength.js): starter WAA per
//     lineup slot, top 5 SP / top 8 RP, z and rank within the league, lenses
//     'mlb' (ours "Now") and 'farm' (ours "Farm"). Ours' depth-weighted WAR
//     strength engine is not ported.
//   - The fit baseline is his FV engine's listed potential (or, with the Future
//     Value toggle, his projected peak) in display WAA, not ours' WAR P / v21 FV.
//   - "Above replacement" (ours: fit > 0 on WAR) is fit + the potential role's
//     replacement offset > 0, with his engine's per-league offsets.
// The bonus/penalty constants are ours' (🟡 calibrated on ours' WAR boards,
// not re-checked on his engine). They are additive win deltas, so the unit
// carries over; their size relative to his spread was not checked.
// ============================================================================
import { getPos, isPitcher, isEligible, getProne } from './accessors.js';

export const SCOUT_POSITIONS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'SP', 'RP'];
const HITTER_POS = ['C', '1B', '2B', '3B', 'SS', 'LF', 'CF', 'RF', 'DH'];

// 🟡 ours' SMART_RANK_TUNING (constants.js).
export const FIT_TUNING = {
  RP_ADJUST_SCALE: 0.375,     // IP_RP / IP_SP on ours' calibration
  ORG_NEED_BONUS_SCALE: 0.12, // wins per SD of positional weakness
  PRONE_PENALTY: { 'Iron Man': -0.5, Durable: -0.3, Normal: 0, Fragile: 0.9, Wrecked: 2.0 },
  INT_BONUS: 0.15,            // wins per 10 points of intangibles grade
};
// 🟡 ours: a position is a trade opportunity when the scouted club is above
// league average, mine is below, and the gap is at least 1.0 SD.
export const TRADE_GAP_SD = 1.0;

// Roster position for the comparison. His POS carries OOTP's 'CL' (and 'MR' on
// some exports); both are relievers.
export const rosterPos = (p) => {
  const pos = String(getPos(p) || '').toUpperCase();
  return pos === 'CL' || pos === 'MR' ? 'RP' : pos;
};

export const eligiblePositions = (p) =>
  (isPitcher(p) ? [rosterPos(p)] : HITTER_POS.filter((pos) => isEligible(p, pos)));

// z per position for one team from his buildPositionalStrength cells.
export const teamZ = (build, team) => {
  const cells = build?.cells?.[team] || {};
  const out = {};
  for (const pos of SCOUT_POSITIONS) out[pos] = Number.isFinite(cells[pos]?.z) ? cells[pos].z : null;
  return out;
};
export const teamRanks = (build, team) => {
  const cells = build?.cells?.[team] || {};
  const out = {};
  for (const pos of SCOUT_POSITIONS) out[pos] = Number.isFinite(cells[pos]?.rank) ? cells[pos].rank : null;
  return out;
};

// ours strength.js calcOrgNeed: need = max(0, -z); 0 at or above average.
export const orgNeedFromZ = (z) => {
  const need = {};
  for (const pos of SCOUT_POSITIONS) need[pos] = Math.max(0, -(z[pos] ?? 0));
  return need;
};

export const weakPositions = (myZ) => new Set(SCOUT_POSITIONS.filter((pos) => (myZ[pos] ?? 0) < 0));

export const tradeOpportunities = (scoutZ, myZ) =>
  SCOUT_POSITIONS.filter((pos) => {
    const theirs = scoutZ[pos] ?? 0, ours = myZ[pos] ?? 0;
    return theirs > 0 && ours < 0 && (theirs - ours) >= TRADE_GAP_SD;
  });

// ours applySmartRank, restricted to the four toggles the Scout page offers
// (Future Value, Org Need, Injury, Intangibles). `entry` carries _baseVal
// (listed potential), _fv (projected peak), _role ('sp' | 'rp' | null) and
// _intangibles (20-80 grade or null).
export function fitScore(entry, toggles, orgNeed) {
  const anyToggle = toggles.fv || toggles.orgNeed || toggles.injury || toggles.intangibles;
  if (!anyToggle) return entry._baseVal ?? null;
  const adjScale = entry._role === 'rp' ? FIT_TUNING.RP_ADJUST_SCALE : 1;
  let score = toggles.fv ? (entry._fv ?? entry._baseVal ?? 0) : (entry._baseVal ?? 0);
  if (toggles.orgNeed && orgNeed) {
    let maxNeed = orgNeed[rosterPos(entry)] ?? 0;
    for (const pos of eligiblePositions(entry)) maxNeed = Math.max(maxNeed, orgNeed[pos] ?? 0);
    score += adjScale * FIT_TUNING.ORG_NEED_BONUS_SCALE * maxNeed;
  }
  if (toggles.injury) {
    const prone = getProne(entry);
    score -= adjScale * (prone ? (FIT_TUNING.PRONE_PENALTY[prone] ?? 0) : 0);
  }
  if (toggles.intangibles && entry._intangibles != null) {
    score += adjScale * ((entry._intangibles - 50) / 10) * FIT_TUNING.INT_BONUS;
  }
  return score;
}

// Ours kept a trade target only when its fit was above 0 on the WAR scale, i.e.
// above replacement. Fit here is WAA, so the test adds back the replacement
// offset of the role the potential is priced on. No offset known → WAA > 0.
export const aboveReplacement = (fit, replOffset) =>
  fit != null && Number.isFinite(fit) && fit + (Number.isFinite(replOffset) ? replOffset : 0) > 0;
