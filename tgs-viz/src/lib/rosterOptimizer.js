/**
 * TGS Roster Optimizer
 *
 * Builds optimal 26-man roster to maximize wins:
 * - 13 position players chosen to MAXIMIZE the blended platoon objective
 *   vrShare·(best 9 vs RHP) + (1−vrShare)·(best 9 vs LHP), seeded from:
 *   - 9 everyday starters on weighted WAA (C, SS, CF, 2B, 3B, LF, RF, 1B, DH)
 *   - Backup C (second catcher)
 *   - Utility IF (SS+2B+3B eligible — one glove covers the whole infield)
 *   - Utility OF (CF plus a corner)
 *   - Platoon bat (biggest vL upgrade over an everyday starter)
 *   then improved by bounded swap search (see improveRosterByBlend). Every
 *   candidate 13 must keep that bench decomposition (benchComposition) — the
 *   bench contract is a hard constraint, not a soft preference.
 *
 * - 13 pitchers
 *   - 5 SP (starting pitchers)
 *   - 8 RP (relief pitchers)
 *
 * Two batting lineups generated: vs RHP and vs LHP
 * Each uses split-specific WAA to pick the best 9 starters, then
 * orders them using "The Book" sabermetric methodology:
 *
 * The Book batting order (user-corrected):
 *   Slot 1: Best OBP (leadoff / table setter)
 *   Slot 2: Best wOBA (best pure hitter)
 *   Then rank all 9 by wOBA (1=best, 9=worst):
 *   Slot 3: wOBA rank #5
 *   Slot 4: wOBA rank #3
 *   Slot 5: wOBA rank #4
 *   Slot 6: wOBA rank #6
 *   Slot 7: wOBA rank #7
 *   Slot 8: wOBA rank #9 (worst)
 *   Slot 9: wOBA rank #8
 *
 * Uses OPTIMAL ASSIGNMENT to maximize total position-specific WAA
 * across all 9 positions simultaneously, rather than greedy assignment
 * which can put players in suboptimal positions.
 *
 * Roster selection uses WAA (offense + defense).
 * Batting order uses wOBA (pure hitting) and OBP (on-base ability).
 */

// ============================================================
// Column Constants
// ============================================================

import { leagueCalib } from './leagueCalib.js';

const WAA_COLUMNS = {
  wtd: ['C WAA wtd', '1B WAA wtd', '2B WAA wtd', '3B WAA wtd', 'SS WAA wtd', 'LF WAA wtd', 'CF WAA wtd', 'RF WAA wtd', 'DH WAA wtd', 'Max WAA wtd'],
  vR: ['C WAA vR', '1B WAA vR', '2B WAA vR', '3B WAA vR', 'SS WAA vR', 'LF WAA vR', 'CF WAA vR', 'RF WAA vR', 'DH WAA vR', 'Max WAA vR'],
  vL: ['C WAA vL', '1B WAA vL', '2B WAA vL', '3B WAA vL', 'SS WAA vL', 'LF WAA vL', 'CF WAA vL', 'RF WAA vL', 'DH WAA vL', 'Max WAA vL'],
};

const OBP_COLUMNS = { vR: 'OBP vR', vL: 'OBP vL', wtd: 'OBP wtd' };
const WOBA_COLUMNS = { vR: 'wOBA vR', vL: 'wOBA vL', wtd: 'wOBA wtd' };

const PITCHER_WAA_SP_COL = 'WAA wtd';
const PITCHER_WAA_RP_COL = 'WAA wtd RP';

// Positions to fill (C assigned separately, DH is open to anyone)
const FIELD_POSITIONS = ['C', 'SS', 'CF', '2B', '3B', 'LF', 'RF', '1B'];
const ALL_LINEUP_POSITIONS = ['C', 'SS', 'CF', '2B', '3B', 'LF', 'RF', '1B', 'DH'];

// ============================================================
// Helper Functions
// ============================================================

/**
 * Find the best WAA value from a set of columns for a player.
 */
function findBestWAA(player, columns) {
  let bestWAA = -Infinity;
  let bestCol = null;

  for (const col of columns) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val > bestWAA) {
      bestWAA = val;
      bestCol = col;
    }
  }

  return bestWAA === -Infinity ? { waa: null, column: null } : { waa: bestWAA, column: bestCol };
}

/**
 * Determine what positions a hitter can play based on eligibility columns.
 */
function getEligiblePositions(player) {
  const positions = [];
  const posMap = {
    'C': 'C Eligible',
    '1B': '1B Eligible',
    '2B': '2B Eligible',
    '3B': '3B Eligible',
    'SS': 'SS Eligible',
    'LF': 'LF Eligible',
    'CF': 'CF Eligible',
    'RF': 'RF Eligible',
  };

  for (const [pos, eligCol] of Object.entries(posMap)) {
    const eligible = player[eligCol];
    if (eligible === true || eligible === 'True' || eligible === 'TRUE') {
      positions.push(pos);
    } else if (eligible === undefined || eligible === null || eligible === '') {
      // Flag genuinely MISSING (not an explicit False) → fall back to a non-zero position WAA.
      // An explicit False means OOTP says he can't field there, so trust it: the engine still
      // computes a (negative) WAA from any defensive rating, and treating that as "eligible"
      // was slotting non-catchers (e.g. a 25-framing 3B) as backup catchers.
      const waaVal = parseFloat(player[`${pos} WAA wtd`]);
      if (!isNaN(waaVal) && waaVal !== 0) positions.push(pos);
    }
  }

  // Everyone can DH
  positions.push('DH');
  return positions;
}

/**
 * Get WAA for a specific player at a specific position for a specific split.
 */
function getPositionWAAForSplit(player, position, split) {
  const col = `${position} WAA ${split}`;
  const val = parseFloat(player[col]);
  return isNaN(val) ? -Infinity : val;
}

/**
 * Get the WAA for a specific player at a specific position.
 */
function getPositionWAA(player, position, waaColumns) {
  for (const col of waaColumns) {
    const colLower = col.toLowerCase();
    const posLower = position.toLowerCase();
    if (colLower.includes(posLower) && (colLower.includes('waa') || colLower.includes('war'))) {
      const val = parseFloat(player[col]);
      if (!isNaN(val)) return val;
    }
  }
  return getMaxWAA(player, waaColumns);
}

/**
 * Get the maximum WAA value from a set of columns.
 */
function getMaxWAA(player, waaColumns) {
  let max = -Infinity;
  for (const col of waaColumns) {
    const val = parseFloat(player[col]);
    if (!isNaN(val) && val > max) max = val;
  }
  return max === -Infinity ? 0 : max;
}

// ============================================================
// Position Eligibility Checks
// ============================================================

function isEligible(player, pos) {
  const eligible = player[`${pos} Eligible`];
  return eligible === true || eligible === 'True' || eligible === 'TRUE';
}

function canPlaySS(player) {
  return isEligible(player, 'SS');
}

function canPlayCF(player) {
  return isEligible(player, 'CF');
}

function canPlayIF(player) {
  return ['2B', '3B', 'SS'].some(pos => isEligible(player, pos));
}

function canPlayOF(player) {
  return ['LF', 'CF', 'RF'].some(pos => isEligible(player, pos));
}

/**
 * Can play ALL three non-1B infield positions: SS, 2B, 3B.
 * Required for Utility Infielder bench role.
 */
function canPlayAllIF(player) {
  return ['SS', '2B', '3B'].every(pos => isEligible(player, pos));
}

/**
 * Can play CF plus at least one corner OF position (LF or RF).
 * Required for Utility Outfielder bench role.
 */
function canPlayCFAndCornerOF(player) {
  if (!isEligible(player, 'CF')) return false;
  return isEligible(player, 'LF') || isEligible(player, 'RF');
}

// ============================================================
// Optimal Position Assignment (replaces greedy)
// ============================================================

/**
 * Optimally assign players to positions to maximize total position-specific WAA.
 *
 * EXACT bitmask DP over the (≤9) position slots: dp[player i][mask of filled
 * positions] = best score. Each filled slot carries a large bonus so the DP
 * fills as many positions as possible FIRST, then maximizes WAA — a fillable
 * slot never loses to an empty one, even when every candidate is negative.
 * O(players × 2^9 × 9), so it is both faster AND strictly better than the old
 * truncated branch-and-bound (which capped branching at 5 per slot). Exactness
 * matters doubly now: the roster swap search compares these totals directly,
 * so the evaluator must be deterministic-optimal or swaps could thrash.
 *
 * @param {Array} candidates - scored hitters (with _positions, etc.)
 * @param {string} split - 'wtd', 'vR', or 'vL'
 * @param {Set} excludeIds - player IDs already taken (e.g., catchers)
 * @param {Object} preAssigned - positions already assigned { pos: player }
 * @returns {Object} - { assignments: { pos: player }, totalWAA: number }
 */
function optimalPositionAssignment(candidates, split, excludeIds = new Set(), preAssigned = {}) {
  // Determine which positions still need filling
  const positionsToFill = ALL_LINEUP_POSITIONS.filter(p => !preAssigned[p]);
  const nPos = positionsToFill.length;
  const FILL_BONUS = 1e6;   // lexicographic: maximize filled slots, then WAA

  // Get available players (not excluded, not pre-assigned)
  const preAssignedIds = new Set(Object.values(preAssigned).map(p => p.ID || p.Name));
  const available = candidates.filter(h =>
    !excludeIds.has(h.ID || h.Name) && !preAssignedIds.has(h.ID || h.Name)
  );

  // Per-player eligible (posIdx, waa) options for this split.
  const options = available.map(h => {
    const opts = [];
    for (let p = 0; p < nPos; p++) {
      if (!h._positions.includes(positionsToFill[p])) continue;
      const waa = getPositionWAAForSplit(h, positionsToFill[p], split);
      if (waa !== -Infinity) opts.push([p, waa]);
    }
    return opts;
  });

  const nMasks = 1 << nPos;
  const n = available.length;
  // dp[i][mask]: best score after considering first i players with `mask` filled.
  // choice[i][mask]: posIdx the i-th player took (or -1 = unused) on the best path.
  let prev = new Float64Array(nMasks).fill(-Infinity);
  prev[0] = 0;
  const choices = [];
  for (let i = 0; i < n; i++) {
    const cur = new Float64Array(nMasks).fill(-Infinity);
    const choice = new Int8Array(nMasks).fill(-1);
    for (let mask = 0; mask < nMasks; mask++) {
      const base = prev[mask];
      if (base === -Infinity) continue;
      // player unused
      if (base > cur[mask]) { cur[mask] = base; choice[mask] = -1; }
      // player fills one of his eligible open slots
      for (const [p, waa] of options[i]) {
        if (mask & (1 << p)) continue;
        const nm = mask | (1 << p);
        const v = base + waa + FILL_BONUS;
        if (v > cur[nm]) { cur[nm] = v; choice[nm] = p; }
      }
    }
    choices.push(choice);
    prev = cur;
  }

  // Best end mask, then walk back to recover who filled what.
  let bestMask = 0;
  for (let mask = 1; mask < nMasks; mask++) {
    if (prev[mask] > prev[bestMask]) bestMask = mask;
  }

  const assignments = {};
  let totalWAA = 0;

  // Include pre-assigned positions
  for (const [pos, player] of Object.entries(preAssigned)) {
    assignments[pos] = player;
    const waa = getPositionWAAForSplit(player, pos, split);
    totalWAA += waa === -Infinity ? 0 : waa;
  }

  // Reconstruct: replay choices from the last player down. A choice of p at the
  // current mask means player i took slot p (mask had p set on the best path).
  let mask = bestMask;
  for (let i = n - 1; i >= 0 && mask !== 0; i--) {
    const p = choices[i][mask];
    if (p >= 0) {
      const pos = positionsToFill[p];
      const player = available[i];
      assignments[pos] = player;
      totalWAA += getPositionWAAForSplit(player, pos, split);
      mask &= ~(1 << p);
    }
  }

  return { assignments, totalWAA };
}

// ============================================================
// The Book Batting Order
// ============================================================

/**
 * Build a batting order using the corrected "The Book" methodology.
 *
 * Uses wOBA to rank hitters (pure offensive production).
 * Uses OBP to select the leadoff hitter.
 *
 * Slot mapping after OBP leadoff and Best wOBA (#2):
 *   Slot 3 = wOBA rank #5
 *   Slot 4 = wOBA rank #3
 *   Slot 5 = wOBA rank #4
 *   Slot 6 = wOBA rank #6
 *   Slot 7 = wOBA rank #7
 *   Slot 8 = wOBA rank #9 (worst)
 *   Slot 9 = wOBA rank #8
 *
 * @param {Array<{player, position}>} starters - 9 starter entries
 * @param {string} split - 'vR' or 'vL'
 * @returns {Array<{player, position, slot, role, waa, woba, obp}>}
 */
function optimizeBattingOrder(starters, split) {
  if (starters.length === 0) return [];

  const obpCol = OBP_COLUMNS[split];
  const wobaCol = WOBA_COLUMNS[split];

  // Score each starter
  const scored = starters.map(({ player, position }) => ({
    player,
    position,
    splitWAA: getPositionWAAForSplit(player, position, split),
    splitOBP: parseFloat(player[obpCol]) || 0,
    splitWOBA: parseFloat(player[wobaCol]) || 0,
  }));

  // Rank all 9 by wOBA descending (rank 1 = best hitter)
  const rankedByWOBA = [...scored].sort((a, b) => b.splitWOBA - a.splitWOBA);

  // Rank by OBP descending
  const rankedByOBP = [...scored].sort((a, b) => b.splitOBP - a.splitOBP);

  const getId = (s) => s.player.ID || s.player.Name;

  // Per "The Book" (Tango): best 3 hitters go in slots 1, 2, 4.
  // Distribute so OBP is higher in the order, SLG lower.
  // KEY: If the best OBP guy is ALSO the best wOBA guy, he bats 2nd (not 1st).
  // The 2nd slot gets more PAs with runners on (45% vs 36%), so the best
  // all-around hitter does more damage there. Leadoff goes to the 2nd-best OBP guy.
  const bestOBP = rankedByOBP[0];
  const bestWOBA = rankedByWOBA[0];
  const samePlayer = getId(bestOBP) === getId(bestWOBA);

  let leadoff, slotTwo;
  if (samePlayer) {
    // Best OBP = best wOBA → he bats 2nd, second-best OBP leads off
    slotTwo = bestOBP;
    leadoff = rankedByOBP[1] || rankedByWOBA[1];
  } else {
    // Different players → best OBP leads off, best wOBA bats 2nd
    leadoff = bestOBP;
    slotTwo = bestWOBA;
  }

  // Slot-to-rank mapping (1-indexed): slot -> wOBA rank (for slots 3-9)
  const SLOT_TO_RANK = { 3: 5, 4: 3, 5: 4, 6: 6, 7: 7, 8: 9, 9: 8 };

  const order = new Array(10).fill(null); // index 1-9
  const usedIds = new Set();

  // Slot 1: Leadoff
  order[1] = leadoff;
  usedIds.add(getId(leadoff));

  // Slot 2: Best hitter
  order[2] = slotTwo;
  usedIds.add(getId(slotTwo));

  // Slots 3-9: map by wOBA rank
  for (let slot = 3; slot <= 9; slot++) {
    const targetRank = SLOT_TO_RANK[slot]; // 1-based
    let candidate = rankedByWOBA[targetRank - 1]; // 0-based index

    if (!candidate || usedIds.has(getId(candidate))) {
      candidate = rankedByWOBA.find(r => !usedIds.has(getId(r)));
    }

    if (candidate) {
      order[slot] = candidate;
      usedIds.add(getId(candidate));
    }
  }

  // Build labeled result
  const SLOT_LABELS = {
    1: samePlayer ? 'Leadoff (2nd OBP)' : 'Leadoff (OBP)',
    2: samePlayer ? 'Best Hitter (OBP+wOBA)' : 'Best Hitter (wOBA)',
    3: '#5 Hitter',
    4: '#3 Hitter',
    5: '#4 Hitter',
    6: '#6',
    7: '#7',
    8: '#9 (Weakest)',
    9: '#8',
  };

  return order.slice(1).filter(Boolean).map((entry, idx) => ({
    player: entry.player,
    position: entry.position,
    slot: idx + 1,
    role: SLOT_LABELS[idx + 1] || `#${idx + 1}`,
    waa: entry.splitWAA === -Infinity ? 0 : entry.splitWAA,
    woba: entry.splitWOBA,
    obp: entry.splitOBP,
  }));
}

// ============================================================
// Split Lineup Selection (Optimal)
// ============================================================

/**
 * From the 13 rostered hitters, pick the optimal 9 starters for a given split.
 * Uses optimal position assignment to maximize total position-specific WAA.
 *
 * @param {Array} rosteredHitters - The 13 hitters on the roster (enriched)
 * @param {string} split - 'vR' or 'vL'
 * @returns {{ starters: Array<{player, position}>, bench: Array }}
 */
function selectSplitStarters(rosteredHitters, split) {
  // Use optimal assignment to find best player-to-position mapping
  const { assignments } = optimalPositionAssignment(rosteredHitters, split);

  const selectedIds = new Set();
  const starterEntries = [];

  for (const [pos, player] of Object.entries(assignments)) {
    starterEntries.push({ player, position: pos });
    selectedIds.add(player.ID || player.Name);
  }

  const bench = rosteredHitters.filter(h => !selectedIds.has(h.ID || h.Name));

  return { starters: starterEntries, bench };
}

// ============================================================
// Platoon Bat Detection
// ============================================================

/**
 * Identify the best platoon bat candidate from remaining bench players.
 *
 * A platoon bat is a bench player who significantly outperforms a starter
 * at a shared position in one split (vR or vL).
 *
 * @param {Array} benchCandidates - bench players not yet assigned a bench role
 * @param {Object} starters - position -> player map (from weighted roster)
 * @returns {Object|null} - { player, platoonSplit, platoonPosition, waaAdvantage, replacesStarter }
 */
function identifyPlatoonBat(benchCandidates, starters) {
  let bestCandidate = null;
  let bestAdvantage = 0;

  for (const benchPlayer of benchCandidates) {
    const benchPositions = benchPlayer._positions || getEligiblePositions(benchPlayer);

    for (const split of ['vR', 'vL']) {
      for (const pos of benchPositions) {
        const starter = starters[pos];
        if (!starter) continue;

        const benchWAA = getPositionWAAForSplit(benchPlayer, pos, split);
        const starterWAA = getPositionWAAForSplit(starter, pos, split);

        if (benchWAA === -Infinity || starterWAA === -Infinity) continue;

        const advantage = benchWAA - starterWAA;
        if (advantage > bestAdvantage) {
          bestAdvantage = advantage;
          bestCandidate = {
            player: benchPlayer,
            platoonSplit: split,
            platoonPosition: pos,
            waaAdvantage: Math.round(advantage * 100) / 100,
            replacesStarter: starter.Name,
          };
        }
      }
    }
  }

  return bestCandidate;
}

// ============================================================
// Roster-construction helpers (seeds + reserved contract bench)
// ============================================================

const ASSIGN_POOL_CAP = 60;   // only bites for the ALL-orgs view
const _idOf = (h) => h.ID || h.Name;
const _num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : -99; };

// Bound the branch-and-bound input. A single org+level is already small; for ALL
// orgs, use the union of the best weighted, best vR and best vL bats plus every
// catcher (so the backup-C pick is never starved).
function buildAssignmentPool(scored) {
  if (scored.length <= ASSIGN_POOL_CAP) return scored;
  const byWtd = [...scored].sort((a, b) => _num(b['Max WAA wtd']) - _num(a['Max WAA wtd'])).slice(0, ASSIGN_POOL_CAP);
  const byVR = [...scored].sort((a, b) => _num(b['Max WAA vR']) - _num(a['Max WAA vR'])).slice(0, ASSIGN_POOL_CAP);
  const byVL = [...scored].sort((a, b) => _num(b['Max WAA vL']) - _num(a['Max WAA vL'])).slice(0, ASSIGN_POOL_CAP);
  // top catchers only (the starting-C assignment needs the best few, not all ~800
  // catcher-eligible players league-wide — that would balloon the branch-and-bound).
  const cs = scored.filter(h => h._positions.includes('C'))
    .sort((a, b) => _num(b['C WAA wtd']) - _num(a['C WAA wtd'])).slice(0, 8);
  const seen = new Set(), out = [];
  for (const h of [...byWtd, ...byVR, ...byVL, ...cs]) { const id = _idOf(h); if (!seen.has(id)) { seen.add(id); out.push(h); } }
  return out;
}

// The biggest platoon upgrade vs LHP: the non-starter whose vL WAA at a position he
// can play most exceeds the starter's vL WAA there (the McKay -> Macrae case).
function bestPlatoonPartner(pool, excludeIds, startersMap) {
  let best = null;
  for (const h of pool) {
    if (excludeIds.has(_idOf(h))) continue;
    for (const pos of h._positions) {
      const starter = startersMap[pos];
      if (!starter) continue;
      const cand = getPositionWAAForSplit(h, pos, 'vL');
      const inc = getPositionWAAForSplit(starter, pos, 'vL');
      if (cand === -Infinity || inc === -Infinity) continue;
      const gain = cand - inc;
      if (!best || gain > best.gain) best = { player: h, pos, gain };
    }
  }
  return best;
}

// ============================================================
// Blended-objective roster search (the cut maximizes WINS, not a column)
// ============================================================
//
// Projected wins pay vrShare·(best nine vs R from the 13) + (1−vrShare)·(best
// nine vs L from the 13). The cut used to anchor on a single column ('vR'),
// which promoted strict-platoon bats over everyday players on tiny vR edges —
// e.g. Feliz Sánchez (vR −0.57 / vL −2.92) beat Mauricio Galván (−0.59 / −0.59)
// at 3B on a 0.02 vR edge while being ~0.4 wins worse over a full season. So the
// roster is now seeded on the weighted splits, then improved by bounded local
// search on the blended objective itself — platoon-vs-everyday is decided by the
// math, not a heuristic.

const EMPTY_SLOT_PENALTY = 6;   // a fillable lineup slot must never lose to an empty one
const SWAP_EPS = 1e-3;          // strict-improvement threshold (avoids float thrash)
const MAX_SWAPS = 10;           // accepted swaps bound (each pass is one accepted swap)
const SWAP_OUT_CAP = 8;         // try removing only the weakest N rostered bats
const SWAP_IN_WTD = 12;         // outside candidates: best weighted…
const SWAP_IN_SPLIT = 8;        // …plus the best per-split specialists

// The exact quantity the win model pays for a 13-man roster: both split lineups
// re-assigned optimally from the SAME 13, PA-share blended. Unfillable slots are
// penalized so the search can never "improve" by rostering its way out of a position.
function blendedLineupScore(roster13, vrShare) {
  const vR = optimalPositionAssignment(roster13, 'vR');
  const vL = optimalPositionAssignment(roster13, 'vL');
  const missR = ALL_LINEUP_POSITIONS.length - Object.keys(vR.assignments).length;
  const missL = ALL_LINEUP_POSITIONS.length - Object.keys(vL.assignments).length;
  return vrShare * (vR.totalWAA - missR * EMPTY_SLOT_PENALTY)
       + (1 - vrShare) * (vL.totalWAA - missL * EMPTY_SLOT_PENALTY);
}

// ---- Bench-composition contract (hard constraint) ----
// The four non-everyday bench spots must decompose into the original reserved
// roles — backup C (second catcher), utility IF (SS+2B+3B eligible: one glove
// covers the whole infield), utility OF (CF + a corner), flex/platoon — with
// DISTINCT players. Counting starters toward coverage let the swap search sell
// the real bench (trade the utility IF away because the starting 2B happened to
// be SS-eligible), so the contract is checked on the BENCH after the everyday
// nine are lifted out. A role relaxes one tier ONLY when the org genuinely
// cannot bench a qualifier; the relaxation is surfaced via bench roleNotes.
const BENCH_ROLES = ['backupC', 'utilityIF', 'utilityOF'];
const ROLE_TIERS = {
  backupC:   [(h) => h._positions.includes('C')],
  utilityIF: [canPlayAllIF, (h) => h._positions.includes('SS')],
  utilityOF: [canPlayCFAndCornerOF, (h) => h._positions.includes('CF')],
};
const ROLE_COLS = { backupC: 'C WAA wtd', utilityIF: 'SS WAA wtd', utilityOF: 'CF WAA wtd' };
const ROLE_NOTES = {   // per tier; tier 0 = contract met (no note)
  backupC:   [null, 'no second catcher in org'],
  utilityIF: [null, 'no true utility IF (SS+2B+3B) in org — best SS glove', 'no utility IF in org'],
  utilityOF: [null, 'no true utility OF (CF+corner) in org — best CF glove', 'no utility OF in org'],
};

// Strictest tier each role can attempt given the pool. (The seed-feasibility
// loop in optimizeRoster downgrades further when the only qualifiers all start.)
function initialBenchTiers(pool) {
  const n = (f) => pool.filter(f).length;
  const nC = n(h => h._positions.includes('C'));
  const nSS = n(h => h._positions.includes('SS'));
  const nCF = n(h => h._positions.includes('CF'));
  return {
    backupC:   nC >= 2 ? 0 : 1,
    utilityIF: n(canPlayAllIF) >= 1 ? 0 : (nSS >= 2 ? 1 : 2),
    utilityOF: n(canPlayCFAndCornerOF) >= 1 ? 0 : (nCF >= 2 ? 1 : 2),
  };
}

// Decompose a 13 into everyday nine (wtd assignment) + bench, and match the
// bench to the required roles with DISTINCT players (exact backtracking; ≤3
// roles over ~4 bench bats). Returns null when the bench can't honor the deal.
function benchComposition(roster13, tiers) {
  const { assignments } = optimalPositionAssignment(roster13, 'wtd');
  const starterIds = new Set(Object.values(assignments).map(_idOf));
  const bench = roster13.filter(h => !starterIds.has(_idOf(h)));
  const roles = BENCH_ROLES.filter(r => tiers[r] < ROLE_TIERS[r].length);
  const match = {};
  const used = new Set();
  const fill = (i) => {
    if (i >= roles.length) return true;
    const qual = ROLE_TIERS[roles[i]][tiers[roles[i]]];
    for (const h of bench) {
      const id = _idOf(h);
      if (used.has(id) || !qual(h)) continue;
      used.add(id); match[roles[i]] = h;
      if (fill(i + 1)) return true;
      used.delete(id); delete match[roles[i]];
    }
    return false;
  };
  if (!fill(0)) return null;
  return { everyday: assignments, bench, match };
}

// Which single role blocks a roster's composition? (Relax exactly that one.)
function blockedBenchRole(roster13, tiers) {
  if (benchComposition(roster13, tiers)) return null;
  for (const role of BENCH_ROLES) {
    if (tiers[role] >= ROLE_TIERS[role].length) continue;
    const relaxed = { ...tiers, [role]: ROLE_TIERS[role].length };
    if (benchComposition(roster13, relaxed)) return role;
  }
  return BENCH_ROLES.find(r => tiers[r] < ROLE_TIERS[r].length) || null;
}

// A reserved qualifier can get PROMOTED into the everyday nine when the 13 is
// re-assigned (e.g. the reserved utility IF out-hits the seeded 3B), leaving the
// bench without the role again. Repair by pulling in the next-best OUTSIDE
// qualifier (dropping the weakest bench body the contract doesn't claim) until
// the bench holds one — a role tier only relaxes when the org truly runs out of
// benchable qualifiers, never because one seed's assignment shuffled.
function repairSeedBench(roster13, pool, tiers) {
  let current = [...roster13];
  for (let guard = 0; guard < 10; guard++) {
    const blocked = blockedBenchRole(current, tiers);
    if (!blocked) return { roster: current, blocked: null };
    const qual = ROLE_TIERS[blocked][tiers[blocked]];
    const inIds = new Set(current.map(_idOf));
    let add = null, addV = -Infinity;
    for (const h of pool) {
      if (inIds.has(_idOf(h)) || !qual(h)) continue;
      const v = _num(h[ROLE_COLS[blocked]]);
      if (v > addV) { addV = v; add = h; }
    }
    if (!add) return { roster: current, blocked };   // genuinely no benchable qualifier left
    // drop the weakest bench body the rest of the contract doesn't claim
    const relaxedTiers = { ...tiers, [blocked]: ROLE_TIERS[blocked].length };
    const comp = benchComposition(current, relaxedTiers);
    let bench, matched;
    if (comp) {
      bench = comp.bench;
      matched = new Set(Object.values(comp.match).map(_idOf));
    } else {
      const { assignments } = optimalPositionAssignment(current, 'wtd');
      const sIds = new Set(Object.values(assignments).map(_idOf));
      bench = current.filter(h => !sIds.has(_idOf(h)));
      matched = new Set();
    }
    const drop = bench.filter(h => !matched.has(_idOf(h)))
      .sort((a, b) => (a._maxWAA || 0) - (b._maxWAA || 0))[0] || bench[0];
    if (!drop) return { roster: current, blocked };
    current = current.filter(h => _idOf(h) !== _idOf(drop));
    current.push(add);
  }
  return { roster: current, blocked: blockedBenchRole(current, tiers) };
}

// Seed a 13-man roster the reservation way: 9 starters assigned on `split`, then
// the contract bench reserved at the active tiers (best qualifier per role by its
// position column), then the vL platoon partner or best bat, backfilled to size.
// The search below starts from both the 'wtd' and 'vR' seeds, so the final roster
// can never score below either single-column anchoring under the same contract.
const PLATOON_MIN_GAIN = 0.5;
function buildSeedRoster(scored, assignPool, split, totalBatters, tiers) {
  const { assignments } = optimalPositionAssignment(assignPool, split);
  const ids = new Set(Object.values(assignments).map(_idOf));

  for (const role of BENCH_ROLES) {
    if (tiers[role] >= ROLE_TIERS[role].length) continue;   // relaxed to none
    const qual = ROLE_TIERS[role][tiers[role]];
    let best = null, bestV = -Infinity;
    for (const h of scored) {
      if (ids.has(_idOf(h)) || !qual(h)) continue;
      const v = parseFloat(h[ROLE_COLS[role]]);
      if (!isNaN(v) && v > bestV) { bestV = v; best = h; }
    }
    if (best) ids.add(_idOf(best));
  }

  const partner = bestPlatoonPartner(scored, ids, assignments);
  const flex = (partner && partner.gain >= PLATOON_MIN_GAIN)
    ? partner.player
    : scored
        .filter(h => !ids.has(_idOf(h)))
        .sort((a, b) => (b._maxWAA - a._maxWAA) || (b._positions.length - a._positions.length))[0] || null;
  if (flex) ids.add(_idOf(flex));

  while (ids.size < totalBatters) {
    const next = scored.find(h => !ids.has(_idOf(h)));
    if (!next) break;
    ids.add(_idOf(next));
  }
  return scored.filter(h => ids.has(_idOf(h)));
}

// Bounded, deterministic steepest-ascent: swap one rostered bat for one outside
// candidate whenever the blended objective strictly improves AND the trial 13
// still decomposes into the bench contract (benchComposition) — a swap that
// sells the bench for lineup value is rejected outright. A cheap per-candidate
// screen (can he beat any current lineup occupant at a shared position, in
// either split?) keeps the converged-roster pass nearly free for 32-org sweeps.
function improveRosterByBlend(roster13, pool, vrShare, tiers) {
  let current = [...roster13];
  let best = blendedLineupScore(current, vrShare);

  for (let iter = 0; iter < MAX_SWAPS; iter++) {
    const currentIds = new Set(current.map(_idOf));
    const outside = pool.filter(h => !currentIds.has(_idOf(h)));
    if (!outside.length) break;

    // Bounded swap-in candidates: the bats the blend might want.
    const pick = (col, n) => [...outside].sort((a, b) => _num(b[col]) - _num(a[col])).slice(0, n);
    const seen = new Set(); const swapIns = [];
    for (const h of [...pick('Max WAA wtd', SWAP_IN_WTD), ...pick('Max WAA vR', SWAP_IN_SPLIT), ...pick('Max WAA vL', SWAP_IN_SPLIT)]) {
      const id = _idOf(h); if (!seen.has(id)) { seen.add(id); swapIns.push(h); }
    }

    // Screen: a candidate who beats no current lineup occupant at any shared
    // position, in either split, cannot be worth a trial evaluation.
    const curVR = optimalPositionAssignment(current, 'vR').assignments;
    const curVL = optimalPositionAssignment(current, 'vL').assignments;
    const worthTrying = swapIns.filter(h => h._positions.some(pos => {
      const r = curVR[pos] && getPositionWAAForSplit(h, pos, 'vR') > getPositionWAAForSplit(curVR[pos], pos, 'vR');
      const l = curVL[pos] && getPositionWAAForSplit(h, pos, 'vL') > getPositionWAAForSplit(curVL[pos], pos, 'vL');
      return r || l || !curVR[pos] || !curVL[pos];
    }));
    if (!worthTrying.length) break;

    // Steepest ascent: best strictly-improving swap this pass, weakest outs first.
    const outOrder = [...current].sort((a, b) => (a._maxWAA || 0) - (b._maxWAA || 0)).slice(0, SWAP_OUT_CAP);
    let bestSwap = null;
    for (const out of outOrder) {
      const rest = current.filter(h => _idOf(h) !== _idOf(out));
      for (const inn of worthTrying) {
        const trial = [...rest, inn];
        if (!benchComposition(trial, tiers)) continue;   // bench contract is non-negotiable
        const v = blendedLineupScore(trial, vrShare);
        if (v > best + SWAP_EPS && (!bestSwap || v > bestSwap.v)) bestSwap = { v, out, inn };
      }
    }
    if (!bestSwap) break;

    current = current.filter(h => _idOf(h) !== _idOf(bestSwap.out));
    current.push(bestSwap.inn);
    best = bestSwap.v;
  }

  return current;
}

// ============================================================
// Runs / Pythagorean foundation (shared by the win-model lenses)
// ============================================================
//
// The linear model is `G/2 + WAA` (81 at G=162). That is the tangent line to the Pythagorean
// win curve at .500 — faithful in the middle, only bending at the tails. To run
// real Pythagorean we need absolute Runs Scored / Runs Allowed, which we build
// from columns already in the JSON:
//   offense  -> BatR (batting runs vs avg) + BSR (baserunning), per split
//   run env  -> league-average team RA/9 (derived from each team's real staff)
// RS = R0 + lineup offense; RA is pinned so RS-RA EXACTLY equals the linear
// model's run differential ((lineupWAA+pitcherWAA)*RPW) — so Pythagorean and
// Linear agree at average and differ only by the curve, never by a bookkeeping gap.

const PYTHAGENPAT_EXP = 0.287;          // PythagenPat: x = (R/G)^0.287
const SP_INNINGS_SHARE = 0.62;          // ~62% of team innings thrown by the rotation

// ---- Season length (audit B3, corrected 2026-08-05) ----
// MEASURED from the REAL leagues, not the clone-lab archives. The lab archives
// play ~154 (mean W+L: TGS 154.0, BLM ~153.5) and an earlier fix wrongly shipped
// that lab number as the live season length. The real leagues both play 162:
//   TGS — banked 2044 actuals (backtest/actuals/TGS/2044/pitching.csv,
//         split_id=1): all 32 teams exactly W+L=162 and GS=162; league total
//         W = 2592 = 32x81.
//   BLM — real league on StatsPlus (statsplus.net/blm/api/playerpitchstatsv2/
//         ?year=2026&lid=144&split=1, last completed season): all 30 teams
//         exactly W+L=162 and GS=162; league total W+L = 4860 = 30x162.
// NOTE: archive-frame calibration (RPW, luckSD, workloads in leagueCalib /
// currency_fit.py) was fitted on archive wins/runs where 154 IS the right G —
// those fits are unaffected. Only this live presentation layer uses G below.
// Games per season is per-league config keyed by the league id the pages
// already carry; unknown leagues fall back to MLB's 162.
export const LEAGUE_GAMES = { TGS: 162, BLM: 162 };
export const DEFAULT_GAMES = 162;
export function leagueGames(league) {
  return LEAGUE_GAMES[league] || DEFAULT_GAMES;
}

// League run environment = average team runs/game. Use each MLB team's ACTUAL
// staff (top 5 SP by SP-WAA + top 8 RP by RP-WAA), innings-weighted, then average
// across teams. Avoids the 40-man scrub tail that inflates a naive league mean.
function leagueRunsPerGame(allPitchers) {
  const byOrg = {};
  for (const p of allPitchers) {
    if ((p.Lev || '').toUpperCase() !== 'MLB') continue;
    const org = p.ORG || '?';
    (byOrg[org] = byOrg[org] || []).push(p);
  }
  const teamRG = [];
  for (const org in byOrg) {
    const arms = byOrg[org];
    const sp = [...arms].sort((a, b) => (_num(b['WAA wtd']) - _num(a['WAA wtd']))).slice(0, 5)
      .map(p => parseFloat(p['RA/9 wtd'])).filter(v => Number.isFinite(v) && v > 0 && v < 15);
    const rp = [...arms].sort((a, b) => (_num(b['WAA wtd RP']) - _num(a['WAA wtd RP']))).slice(0, 8)
      .map(p => parseFloat(p['RA/9 wtd RP'])).filter(v => Number.isFinite(v) && v > 0 && v < 15);
    if (sp.length < 3 || rp.length < 3) continue;
    const spRG = sp.reduce((a, b) => a + b, 0) / sp.length;
    const rpRG = rp.reduce((a, b) => a + b, 0) / rp.length;
    teamRG.push(SP_INNINGS_SHARE * spRG + (1 - SP_INNINGS_SHARE) * rpRG);
  }
  if (!teamRG.length) return 4.5;
  return teamRG.reduce((a, b) => a + b, 0) / teamRG.length;
}

// Runs per win. audit D9: ONE fitted RPW per league (archive wins-on-run-diff
// regression, mid-range spec — see leagueCalib.js), the SAME value the python
// engine now uses as Data Points H30, so WAA columns and these win models price
// a win identically. The Tango tangent (1.5*lgRG+3) remains only as the
// fallback for leagues without a fitted value.
function runsPerWin(lgRG, league = null) {
  if (league) {
    const c = leagueCalib(league);
    if (Number.isFinite(c.rpw)) return c.rpw;
  }
  return 1.5 * lgRG + 3;
}

// PA-weighted offensive runs for a split batting order. audit D9 (faithful
// RS/RA decomposition): the DH slot contributes its DH-specific batting runs
// ('DH BatR', the engine's DH-discounted line) and the engine's 0.98 BSR
// factor — matching how 'DH WAA' is built — instead of the fielder-frame BatR.
function lineupOffRuns(order, split) {
  return order.reduce((s, e) => {
    const isDH = e.position === 'DH';
    const brCol = isDH ? `DH BatR ${split}` : `BatR ${split}`;
    let br = parseFloat(e.player[brCol]);
    if (isDH && !Number.isFinite(br)) br = parseFloat(e.player[`BatR ${split}`]);
    const bs = parseFloat(e.player[`BSR ${split}`]);
    return s + (Number.isFinite(br) ? br : 0)
             + (Number.isFinite(bs) ? bs : 0) * (isDH ? 0.98 : 1);
  }, 0);
}

// Pythagorean win% for a given RS/RA (PythagenPat exponent). `games` sets the
// per-game normalization of the exponent (B3: the league's measured G).
function pythWinPct(RS, RA, games = DEFAULT_GAMES) {
  const rpg = Math.max((RS + RA) / games, 0.5);
  const x = Math.pow(rpg, PYTHAGENPAT_EXP);
  const rs = Math.pow(Math.max(RS, 1), x);
  const ra = Math.pow(Math.max(RA, 1), x);
  return rs / (rs + ra);
}

// Build the team's RS / RA from the two platoon lineups + pitching, faithful to
// the linear run differential. Returns absolute runs plus the Pythagorean wins.
// `games` (B3) scales the league run baseline AND the win total to the real
// season length (the league's measured G — 162 for both real leagues).
function buildRunsModel({ vROrder, vLOrder, vrShare, weightedLineupWAA, totalPitcherWAA, lgRG, leagueOffset = 0, games = DEFAULT_GAMES, league = null }) {
  const R0 = lgRG * games;
  const RPW = runsPerWin(lgRG, league);   // D9: fitted per-league RPW
  const offRAA = vrShare * lineupOffRuns(vROrder, 'vR') + (1 - vrShare) * lineupOffRuns(vLOrder, 'vL');
  const netRD = (weightedLineupWAA + totalPitcherWAA - leagueOffset) * RPW;   // linear run diff, league-normalized
  const RS = R0 + offRAA;
  const RA = Math.max(RS - netRD, R0 * 0.3);
  const wpct = pythWinPct(RS, RA, games);
  return { R0, RPW, lgRG, offRAA, netRD, RS, RA, wpct, games, pythWins: games * wpct };
}

// ---- Monte Carlo: season win distribution + playoff odds ----
// Each sim perturbs RS/RA by projection uncertainty, recomputes the Pythagorean
// true-talent win%, then plays a full season of Bernoulli games (the league's
// real G — B3). Seeded for reproducibility.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function _hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function monteCarloSeason({ RS, RA, games = DEFAULT_GAMES }, seedStr, N = 2500, extras = {}) {
  const rng = mulberry32(_hashSeed(seedStr));
  const gauss = () => {
    // Box-Muller
    let u = 0, v = 0;
    while (u === 0) u = rng();
    while (v === 0) v = rng();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
  const sdR = Math.max(15, 0.035 * ((RS + RA) / 2));   // projection uncertainty per side
  // audit D9: the Bernoulli season below only carries the binomial win floor
  // (~sqrt(G)/2); the sim's MEASURED fixed-talent win SD (leagueCalib.luckSD,
  // from the clone archive's across-year spread) is wider. `luckRuns` is the
  // per-side run noise that closes exactly that gap (derived in optimizeRoster).
  // audit D6: `rpRunsRA` adds the measured RP talent-residual spread (what the
  // 2044 backtest says RP projections still miss) on the runs-allowed side.
  const luckRuns = extras.luckRuns || 0;
  const rpRunsRA = extras.rpRunsRA || 0;
  const sdRS = Math.sqrt(sdR * sdR + luckRuns * luckRuns);
  const sdRA = Math.sqrt(sdR * sdR + luckRuns * luckRuns + rpRunsRA * rpRunsRA);
  const G = games;
  const wins = new Array(N);
  for (let i = 0; i < N; i++) {
    const rs = Math.max(300, RS + gauss() * sdRS);
    const ra = Math.max(300, RA + gauss() * sdRA);
    let p = pythWinPct(rs, ra, G);
    p = Math.min(0.99, Math.max(0.01, p));
    let w = 0;
    for (let g = 0; g < G; g++) if (rng() < p) w++;
    wins[i] = w;
  }
  wins.sort((a, b) => a - b);
  const at = q => wins[Math.min(N - 1, Math.max(0, Math.floor(q * N)))];
  const mean = wins.reduce((a, b) => a + b, 0) / N;
  const sd = Math.sqrt(wins.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (N - 1));
  const ge = t => wins.filter(w => w >= t).length / N;
  // B3: the playoff-odds thresholds are WIN-PERCENTAGE equivalents of the
  // familiar 162-game milestones, scaled to the league's measured G. At G=162
  // (both real leagues) the thresholds equal the literal milestones.
  const t = (w162) => Math.round(w162 * G / DEFAULT_GAMES);
  const thresholds = { pGE85: t(85), pGE88: t(88), pGE90: t(90), pGE95: t(95), pGE100: t(100) };
  // histogram: bucket into win bins for the chart
  const lo = wins[0], hi = wins[N - 1];
  const hist = [];
  for (let b = lo; b <= hi; b++) hist.push({ wins: b, count: 0 });
  for (const w of wins) hist[w - lo].count++;
  return {
    N, games: G, mean, sd, median: at(0.50), p10: at(0.10), p90: at(0.90), floor: at(0.05), ceiling: at(0.95),
    pPlayoff: ge(thresholds.pGE90),
    pGE85: ge(thresholds.pGE85), pGE88: ge(thresholds.pGE88), pGE90: ge(thresholds.pGE90),
    pGE95: ge(thresholds.pGE95), pGE100: ge(thresholds.pGE100),
    thresholds,   // the actual win counts each pGE* was evaluated at (for UI labels)
    hist,
  };
}

// ---- Marginal-lever: where does a win come from cheapest? ----
function marginalLevers({ RS, RA, games = DEFAULT_GAMES }) {
  const w = (rs, ra) => games * pythWinPct(rs, ra, games);
  const base = w(RS, RA);
  const offPer10 = w(RS + 10, RA) - base;     // +10 runs of offense
  const prevPer10 = w(RS, RA - 10) - base;    // -10 runs allowed
  return {
    offPer10, prevPer10,
    lean: offPer10 >= prevPer10 ? 'offense' : 'run prevention',
    edge: Math.abs(offPer10 - prevPer10),
  };
}

// Best in-org call-up upgrade over each rostered spot (approximate, holds others
// fixed). Surfaces the single biggest internal lever, or none if the MLB roster
// already IS the org's best (the common, informative case).
function callupUpgrades({ everydayStarters, startingPitchers, reliefPitchers, pool, pitcherPool, rosteredIds, vrShare, RPW, RS, RA, games = DEFAULT_GAMES }) {
  const dPyth = (dRuns) => games * (pythWinPct(RS + dRuns / 2, RA - dRuns / 2, games) - pythWinPct(RS, RA, games));
  const ups = [];
  // hitters: best non-rostered in-org who beats an everyday starter at his position
  for (const [pos, starter] of Object.entries(everydayStarters)) {
    const sVR = getPositionWAAForSplit(starter, pos, 'vR');
    const sVL = getPositionWAAForSplit(starter, pos, 'vL');
    let best = null;
    for (const h of pool) {
      if (rosteredIds.has(_idOf(h)) || !h._positions.includes(pos)) continue;
      const cVR = getPositionWAAForSplit(h, pos, 'vR');
      const cVL = getPositionWAAForSplit(h, pos, 'vL');
      if (cVR === -Infinity) continue;
      const gainWAA = vrShare * (cVR - sVR) + (1 - vrShare) * (cVL - sVL);
      if (gainWAA > 0 && (!best || gainWAA > best.gainWAA)) best = { player: h, gainWAA, pos };
    }
    if (best) ups.push({ kind: 'bat', pos, name: best.player.Name, over: starter.Name, dWins: dPyth(best.gainWAA * RPW) });
  }
  // pitchers: best non-rostered SP / RP beating the weakest rostered one
  const weakSP = startingPitchers[startingPitchers.length - 1];
  const weakRP = reliefPitchers[reliefPitchers.length - 1];
  for (const [role, weak, col] of [['SP', weakSP, '_spWAA'], ['RP', weakRP, '_rpWAA']]) {
    if (!weak) continue;
    let best = null;
    for (const p of pitcherPool) {
      if (rosteredIds.has(_idOf(p))) continue;
      if (role === 'SP' && p._canStart === false) continue;   // no SP projection = can't be a rotation upgrade
      const v = role === 'SP' ? p._spWAA : p._rpWAA;
      const gain = v - (weak[col] || 0);
      if (gain > 0 && (!best || gain > best.gain)) best = { player: p, gain };
    }
    if (best) ups.push({ kind: role.toLowerCase(), pos: role, name: best.player.Name, over: weak.Name, dWins: dPyth(best.gain * RPW) });
  }
  ups.sort((a, b) => b.dWins - a.dWins);
  return ups.filter(u => u.dWins > 0.05).slice(0, 4);
}

// ---- Injury exclusion: currently-hurt players (any DL signal = out) ----
// Distinct from the Durability lens: Durability HAIRCUTS value by injury proneness;
// this removes players who are hurt RIGHT NOW so the roster is picked from healthy
// bodies only. Missing fields = healthy (offline leagues carry no injury data).
export function isInjured(p) {
  // ONLY the DL flags mean "can't play". DLDays is a recovery-time countdown that can
  // stay >0 after a player is activated (e.g. healed early / playing through it), so it
  // must never gate the roster on its own — it's display info for players who ARE on the DL.
  if (p.OnDL === true || p.OnDL === 'Yes') return true;
  if (p.OnDL60 === true || p.OnDL60 === 'Yes') return true;
  return false;
}

// Stable identity for a player across renders/pools. Prefer the real ID; fall back to
// Name. Used to key manual injury overrides (activate a DL guy before StatsPlus updates)
// so the SAME key computed in the UI and in the optimizer's filter always agree.
export function playerKey(p) {
  return String(p.ID ?? p.PlayerID ?? p.Name ?? '');
}

// Does this league's data carry injury fields at all? (Field PRESENCE, not truthiness —
// a league where everyone happens to be healthy still supports the toggle.)
export function leagueHasInjuryData(hitters, pitchers) {
  const hasFields = (p) => p.OnDL !== undefined || p.OnDL60 !== undefined || p.DLDays !== undefined;
  return hitters.some(hasFields) || pitchers.some(hasFields);
}

// ---- Durability: expected playing-time factor from proneness + current injury ----
const PRONE_FACTOR = { 'Iron Man': 0.99, 'Durable': 0.96, 'Normal': 0.90, 'Fragile': 0.80, 'Wrecked': 0.68 };
function durabilityFactor(p) {
  let f = PRONE_FACTOR[p.Prone] ?? 0.90;
  if (p.OnDL === true || p.OnDL === 'Yes') f *= 0.85;
  const dl = parseFloat(p.DLDays);
  if (Number.isFinite(dl) && dl > 0) f *= Math.max(0.55, 1 - dl / 365);
  return Math.max(0.4, Math.min(1, f));
}
// Return a clone with value/counting columns scaled by the durability factor so
// the SAME selection + scoring pipeline becomes playing-time-aware. Rates (wOBA,
// RA/9) are left alone — a fragile player isn't worse per PA, he plays less.
function applyDurability(p) {
  const f = durabilityFactor(p);
  const o = { ...p, _dur: f };
  if (f >= 0.999) return o;
  for (const k in o) {
    if (k === '_dur') continue;
    if (k.includes('WAA') || k.includes('WAP') || k.startsWith('BatR ') || k.startsWith('BSR ')) {
      const v = parseFloat(o[k]);
      if (Number.isFinite(v) && v > 0) o[k] = v * f;   // only haircut positive value
    }
  }
  return o;
}

// ============================================================
// Main Roster Optimization
// ============================================================

/**
 * Build the optimal 26-man roster and generate split lineups.
 *
 * @param {Array} hitters - All available hitter data
 * @param {Array} pitchers - All available pitcher data
 * @param {Object} options - { teamOrg, levelFilter }
 * @returns {Object} Optimized roster with split lineups
 */
export function optimizeRoster(hitters, pitchers, options = {}) {
  const {
    numStartingPitchers = 5,
    numReliefPitchers = 8,
    totalBatters = 13,
    teamOrg = null,
    levelFilter = null,
    vrShare = null,   // league's real "OVR vR" season split (from metadata); falls back below
    durabilityWeighted = false,   // haircut value by injury proneness + playing time, then re-pick
    excludeInjured = false,       // drop currently-hurt players (OnDL / 60-day / DL days) BEFORE selection
    clearedInjured = null,        // Set of playerKey()s to treat as HEALTHY even while flagged on the DL
                                  // (manual "he's back this sim" override; only meaningful when excludeInjured)
    leagueOffset = 0,             // mean optimized winBasis across the league; subtracted so wins are
                                  // zero-sum (every rival also fields its best 26). 0 = raw roster strength.
    league = null,                // league id ('TGS' | 'BLM') — selects games/season (B3)
    games = null,                 // explicit games override; defaults from LEAGUE_GAMES[league] → 162
  } = options;

  // B3: season length. MEASURED from the real leagues (162 for both — see
  // LEAGUE_GAMES) — base wins are G/2 and every win-model lens plays G games.
  const G = games || leagueGames(league);

  // Team platoon weight: fraction of season PA vs RHP. Real value comes from the sheet
  // metadata (TGS "OVR vR" = 0.7368); fall back to it if not supplied.
  const TEAM_VR_SHARE = (typeof vrShare === 'number' && vrShare > 0 && vrShare < 1) ? vrShare : 0.7368;
  const TEAM_VL_SHARE = 1 - TEAM_VR_SHARE;

  // ---- Filter players by org/level ----
  let availableHitters = [...hitters];
  let availablePitchers = [...pitchers];

  if (teamOrg) {
    availableHitters = availableHitters.filter(h =>
      (h.ORG || '').toLowerCase().includes(teamOrg.toLowerCase())
    );
    availablePitchers = availablePitchers.filter(p =>
      (p.ORG || '').toLowerCase().includes(teamOrg.toLowerCase())
    );
  }

  if (levelFilter) {
    availableHitters = availableHitters.filter(h =>
      (h.Lev || '').toLowerCase().includes(levelFilter.toLowerCase())
    );
    availablePitchers = availablePitchers.filter(p =>
      (p.Lev || '').toLowerCase().includes(levelFilter.toLowerCase())
    );
  }

  // Injury exclusion: pick the roster from healthy players only. Applied AFTER the
  // org/level filter and BEFORE scoring, so every downstream step (13 bats, both
  // platoon lineups, rotation, bullpen, all win models) re-picks from the healthy
  // pool. `leagueOffset` and `lgRG` stay on the full pools — the league baseline
  // must not move just because YOUR roster benches its DL players.
  if (excludeInjured) {
    // A player survives the injury filter if he's healthy OR the user has manually
    // cleared him (activated a DL guy who's back this sim before StatsPlus catches up).
    const healthyOrCleared = (p) => !isInjured(p) || (clearedInjured && clearedInjured.has(playerKey(p)));
    availableHitters = availableHitters.filter(healthyOrCleared);
    availablePitchers = availablePitchers.filter(healthyOrCleared);
  }

  // League run environment from the FULL (unfiltered, unscaled) pitcher pool — the
  // Pythagorean baseline shouldn't move when you switch teams or apply durability.
  const lgRG = leagueRunsPerGame(pitchers);

  // Durability lens: haircut each player's value by expected playing time BEFORE
  // selection, so the same pipeline re-picks the roster (a durable solid bat can
  // now beat a fragile star) and scores it on realistic playing time.
  if (durabilityWeighted) {
    availableHitters = availableHitters.map(applyDurability);
    availablePitchers = availablePitchers.map(applyDurability);
  }

  // ---- Score all hitters by WEIGHTED WAA ----
  // M5: `_war` = WAA + the league's MEASURED **ORG** ("next man up") hitter
  // replacement offset (mean WAA of the marginal rostered bat across orgs —
  // leagueCalib.js replacementOrg). WHY ORG, not MARKET: cut/keep here trades
  // a roster spot against the org's OWN depth, so the internal next-man-up
  // zero is the honest baseline; the (lower) open-market zero belongs to the
  // $ layer only (marketValue.js). Within-role ordering is WAA-identical
  // (constant shift), so selection stays on WAA.
  const _calibEarly = leagueCalib(league);
  const _hOff = (_calibEarly.replacementOrg && Number.isFinite(_calibEarly.replacementOrg.hitter))
    ? _calibEarly.replacementOrg.hitter : 0;
  const wtdColumns = WAA_COLUMNS.wtd;
  const scoredHitters = availableHitters
    .map(h => {
      const maxWAA = getMaxWAA(h, wtdColumns);
      return {
        ...h,
        _maxWAA: maxWAA,
        _war: maxWAA + _hOff,
        _positions: getEligiblePositions(h),   // strict position eligibility (engine-set)
      };
    })
    .filter(h => h._maxWAA !== 0 || h._positions.length > 1)
    .sort((a, b) => b._maxWAA - a._maxWAA);

  // ---- Build roster: seed 13, then maximize the blended objective directly ----
  // Seed = 9 everyday starters on the WEIGHTED position splits + the reserved
  // contract bench (backup C, true utility IF, true utility OF, flex/platoon).
  // Then bounded local search (improveRosterByBlend) swaps bats in/out to maximize
  // vrShare·vR9 + (1−vrShare)·vL9 — the number wins actually track — while every
  // candidate 13 must still decompose into the bench contract (benchComposition).
  // See the search block above for why the cut no longer anchors on any single
  // column (the Sánchez/Galván bug).
  const assignPool = buildAssignmentPool(scoredHitters);

  // STEP 1 — bench-role tiers, then two candidate seeds (everyday-weighted and
  // vR-anchored) that BOTH honor the bench contract, each repaired if its
  // reserved qualifier got promoted into the everyday nine (repairSeedBench).
  // A role relaxes a tier only when even the repair finds no benchable
  // qualifier in the org; both seeds then rebuild at that tier.
  const tiers = initialBenchTiers(scoredHitters);
  let seedWtd, seedVR;
  for (;;) {
    const rW = repairSeedBench(buildSeedRoster(scoredHitters, assignPool, 'wtd', totalBatters, tiers), scoredHitters, tiers);
    const rV = repairSeedBench(buildSeedRoster(scoredHitters, assignPool, 'vR', totalBatters, tiers), scoredHitters, tiers);
    seedWtd = rW.roster;
    seedVR = rV.roster;
    const blocked = rW.blocked ?? rV.blocked;
    if (!blocked) break;
    tiers[blocked] += 1;
  }

  // STEP 2 — the actual cut: bounded local search on the blended objective, from
  // both seeds (basin-sensitive), under the bench contract at the settled tiers.
  const sameSeed = seedWtd.length === seedVR.length
    && seedWtd.every(h => seedVR.some(v => _idOf(v) === _idOf(h)));
  const impWtd = improveRosterByBlend(seedWtd, scoredHitters, TEAM_VR_SHARE, tiers);
  const impVR = sameSeed ? impWtd : improveRosterByBlend(seedVR, scoredHitters, TEAM_VR_SHARE, tiers);
  const improved = blendedLineupScore(impWtd, TEAM_VR_SHARE) >= blendedLineupScore(impVR, TEAM_VR_SHARE)
    ? impWtd : impVR;
  const rosterIdSet = new Set(improved.map(_idOf));
  const rosteredHitters = scoredHitters.filter(h => rosterIdSet.has(_idOf(h)));   // stable order

  // STEP 3 — everyday assignment + bench role labels on the FINAL 13, straight
  // from the contract decomposition. Labels start from the feasibility matching,
  // then each role upgrades to a strictly better unused bench qualifier. A
  // relaxed role carries its roleNote ("no true utility IF in org", …).
  let comp = benchComposition(rosteredHitters, tiers);
  if (!comp) {   // unreachable by construction (seeds + accepted swaps honor the contract)
    const ev = optimalPositionAssignment(rosteredHitters, 'wtd').assignments;
    const sIds = new Set(Object.values(ev).map(_idOf));
    comp = { everyday: ev, bench: rosteredHitters.filter(h => !sIds.has(_idOf(h))), match: {} };
  }
  const everydayStarters = comp.everyday;
  const starters = { ...everydayStarters };

  const benchUsed = new Set(Object.values(comp.match).map(_idOf));
  const roleLabel = {};
  for (const role of BENCH_ROLES) {
    let pick = comp.match[role] || null;
    if (pick) {
      const qual = ROLE_TIERS[role][tiers[role]];
      for (const h of comp.bench) {
        const id = _idOf(h);
        if (benchUsed.has(id) || !qual(h)) continue;
        if (_num(h[ROLE_COLS[role]]) > _num(pick[ROLE_COLS[role]])) {
          benchUsed.delete(_idOf(pick)); benchUsed.add(id); pick = h;
        }
      }
    }
    roleLabel[role] = pick;
  }
  const backupC = roleLabel.backupC || null;
  const utilityIF = roleLabel.utilityIF || null;
  const utilityOF = roleLabel.utilityOF || null;
  const roleNotes = {
    backupC: ROLE_NOTES.backupC[tiers.backupC] || null,
    utilityIF: ROLE_NOTES.utilityIF[tiers.utilityIF] || null,
    utilityOF: ROLE_NOTES.utilityOF[tiers.utilityOF] || null,
  };

  const partner = bestPlatoonPartner(comp.bench, benchUsed, everydayStarters);
  let flexBat = null, platoonBat = null;
  if (partner && partner.gain >= PLATOON_MIN_GAIN) {
    flexBat = partner.player;
    platoonBat = {
      player: partner.player, platoonSplit: 'vL', platoonPosition: partner.pos,
      waaAdvantage: Math.round(partner.gain * 100) / 100,
      replacesStarter: (everydayStarters[partner.pos] || {}).Name,
    };
  } else {
    flexBat = comp.bench
      .filter(h => !benchUsed.has(_idOf(h)))
      .sort((a, b) => (b._maxWAA - a._maxWAA) || (b._positions.length - a._positions.length))[0] || null;
  }
  if (flexBat) benchUsed.add(_idOf(flexBat));

  const benchPlayers = comp.bench.filter(h => !benchUsed.has(_idOf(h)));

  // STEP 4 — split batting orders. Each is the best nine FROM THE 13 for its split
  // (platoons the bench in on both sides), ordered by The Book.
  const vRSplit = selectSplitStarters(rosteredHitters, 'vR');
  const vRBattingOrder = optimizeBattingOrder(vRSplit.starters, 'vR');
  const vLSplit = selectSplitStarters(rosteredHitters, 'vL');
  const vLBattingOrder = optimizeBattingOrder(vLSplit.starters, 'vL');

  // ---- STEP 5: Select Pitchers ----
  // audit D6: RP projected edges are multiplied by the FITTED calibration slope
  // of actual-vs-projected RP outcomes (leagueCalib.rpEdgeSlope; 2044 backtest).
  // The slope is applied around the league-average-RP anchor (WAA 0), so an
  // average RP stays average; ranking within RPs is unchanged (positive
  // multiplier) — what changes is how much pen edges count vs SP/hitters in
  // the win models. NOTE the fitted value is an EXPANSION (1.249): after the
  // D1 S-curve + D2 exponent rebuild the engine still under-spreads real RP
  // outcomes (the audit's 0.82-shrink hypothesis was measured on the OLD
  // engine, whose slope on the same join was 1.83).
  const calib = leagueCalib(league);
  const rpEdgeSlope = Number.isFinite(calib.rpEdgeSlope) ? calib.rpEdgeSlope : 1;
  const scoredPitchers = availablePitchers.map(p => {
    const pos = (p.POS || '').toUpperCase();
    const spWAA = parseFloat(p[PITCHER_WAA_SP_COL]);
    const rpWAA0 = parseFloat(p[PITCHER_WAA_RP_COL]);
    const rpWAA = isNaN(rpWAA0) ? 0 : rpWAA0 * rpEdgeSlope;
    // A missing SP line is NOT a league-average starter. The engine refuses a
    // starter projection to arms that fail the sheet's Starter rule (repertoire
    // + stamina) even when OOTP's POS label says "SP" — pricing that absence as
    // 0 let a projection-less arm (Wisniewski, TB/BLM: POS SP, Starter false,
    // only a -0.35 RP line) out-rank real starters with mildly negative SP
    // lines and take a rotation slot. _canStart gates rotation eligibility;
    // spv stays 0 only for the aggregate bookkeeping of arms never selected.
    const canStart = !isNaN(spWAA);
    const spv = canStart ? spWAA : 0;
    // M5: role-specific WAR in the **ORG** (next-man-up) currency
    // (leagueCalib.js replacementOrg) — internal cut/keep only; the $ layer
    // prices in the MARKET currency instead. Selection within a role stays
    // on WAA.
    const rep = calib.replacementOrg || {};
    const spOff = Number.isFinite(rep.sp) ? rep.sp : 0;
    const rpOff = Number.isFinite(rep.rp) ? rep.rp : 0;
    return {
      ...p,
      _spWAA: spv,
      _rpWAA: rpWAA,
      _canStart: canStart,
      _spWAR: spv + spOff,
      _rpWAR: rpWAA + rpOff,
      _bestWAA: Math.max(canStart ? spv : -Infinity, rpWAA),
      _isStarter: pos === 'SP',
      _isReliever: pos === 'RP' || pos === 'CL' || pos === 'MR',
    };
  });

  const spCandidates = scoredPitchers
    .filter(p => p._canStart && (p._isStarter || !p._isReliever))
    .sort((a, b) => b._spWAA - a._spWAA);

  const startingPitchers = spCandidates.slice(0, numStartingPitchers);
  const spIds = new Set(startingPitchers.map(p => p.ID || p.Name));

  const rpCandidates = scoredPitchers
    .filter(p => !spIds.has(p.ID || p.Name))
    .sort((a, b) => b._rpWAA - a._rpWAA);

  const reliefPitchers = rpCandidates.slice(0, numReliefPitchers);

  // ---- Calculate totals ----
  // audit D9 (workload share): the WAA columns price 5 x 800 BF + 8 x 300 BF of
  // staff innings, but the sim only hands a team's top-5 SP ~94% and top-8 RP
  // ~96-99% of that (measured per league from the clone archives — see
  // leagueCalib.js; the audit's "~0.90 on the pen" hypothesis measured out as
  // rotation 0.93-0.94 / pen 0.96-0.99). The aggregates that feed wins are
  // scaled to the innings the sim actually gives out.
  const spWorkload = Number.isFinite(calib.spWorkload) ? calib.spWorkload : 1;
  const rpWorkload = Number.isFinite(calib.rpWorkload) ? calib.rpWorkload : 1;
  const totalHitterWAA = rosteredHitters.reduce((sum, p) => sum + (p._maxWAA || 0), 0);
  const totalSPWAA = startingPitchers.reduce((sum, p) => sum + (p._spWAA || 0), 0);
  const totalRPWAA = reliefPitchers.reduce((sum, p) => sum + (p._rpWAA || 0), 0);
  const totalPitcherWAA = totalSPWAA * spWorkload + totalRPWAA * rpWorkload;
  const totalRosterWAA = totalHitterWAA + totalPitcherWAA;

  const lineupWAA_vR = vRBattingOrder.reduce((sum, e) => sum + (e.waa || 0), 0);
  const lineupWAA_vL = vLBattingOrder.reduce((sum, e) => sum + (e.waa || 0), 0);

  // Wins track the quantity the selection maximizes: the PA-weighted value of the two
  // platoon lineups (not the sum of all 13 bats, which over-counts the rest-day bench).
  // Base wins are G/2 (81 in the real 162-game leagues — B3).
  const weightedLineupWAA = TEAM_VR_SHARE * lineupWAA_vR + TEAM_VL_SHARE * lineupWAA_vL;
  const estimatedWins = Math.round(G / 2 + weightedLineupWAA + totalPitcherWAA - leagueOffset);

  // ---- Win-model lenses ----
  // Pythagorean RS/RA (faithful to the linear run differential), a Monte Carlo
  // season distribution + playoff odds, and the marginal-lever diagnostics.
  const runs = buildRunsModel({
    vROrder: vRBattingOrder, vLOrder: vLBattingOrder, vrShare: TEAM_VR_SHARE,
    weightedLineupWAA, totalPitcherWAA, lgRG, leagueOffset, games: G, league,
  });
  const pythWins = Math.round(runs.pythWins);
  const clearedTag = (excludeInjured && clearedInjured && clearedInjured.size) ? `+${clearedInjured.size}` : '';
  const seedStr = `${teamOrg || 'ALL'}|${levelFilter || 'ALL'}|${Math.round(runs.RS)}|${Math.round(runs.RA)}|${durabilityWeighted ? 'D' : 'N'}|${excludeInjured ? 'H' : 'A'}${clearedTag}`;
  // audit D9/D6 Monte Carlo widening (all measured — see leagueCalib.js):
  //  luckRuns: per-side run noise closing the gap between the Bernoulli
  //    season's binomial win floor (sqrt(G)/2) and the archive's measured
  //    fixed-talent win SD:  sqrt(luckSD^2 - G/4) wins -> * RPW / sqrt(2) runs.
  //  rpRunsRA: 8 independent pen arms x the measured RP talent residual
  //    (rpTalentSD RA/9 over one pen slot's real innings), RA side only.
  const luckGapWins = Math.sqrt(Math.max((calib.luckSD || 0) ** 2 - G / 4, 0));
  const luckRuns = luckGapWins * runs.RPW / Math.SQRT2;
  const rpRunsRA = Math.sqrt(numReliefPitchers) * (calib.rpTalentSD || 0) / 9
    * ((calib.rpModelIP || 70) * rpWorkload);
  const monteCarlo = monteCarloSeason(runs, seedStr, 2500, { luckRuns, rpRunsRA });
  const levers = marginalLevers(runs);

  const rosteredIds = new Set(rosteredHitters.map(_idOf));
  startingPitchers.forEach(p => rosteredIds.add(_idOf(p)));
  reliefPitchers.forEach(p => rosteredIds.add(_idOf(p)));
  const callups = callupUpgrades({
    everydayStarters, startingPitchers, reliefPitchers,
    pool: scoredHitters, pitcherPool: scoredPitchers,
    rosteredIds, vrShare: TEAM_VR_SHARE, RPW: runs.RPW, RS: runs.RS, RA: runs.RA, games: G,
  });

  // Durability summary (computed for whatever roster this is; `_dur` is present
  // when durabilityWeighted, otherwise derived live for display).
  const durRoster = [
    ...rosteredHitters.map(h => ({ name: h.Name, pos: h.POS, f: h._dur ?? durabilityFactor(h), prone: h.Prone, onDL: h.OnDL === true, dlDays: parseFloat(h.DLDays) || 0 })),
    ...startingPitchers.map(p => ({ name: p.Name, pos: 'SP', f: p._dur ?? durabilityFactor(p), prone: p.Prone, onDL: p.OnDL === true, dlDays: parseFloat(p.DLDays) || 0 })),
    ...reliefPitchers.map(p => ({ name: p.Name, pos: 'RP', f: p._dur ?? durabilityFactor(p), prone: p.Prone, onDL: p.OnDL === true, dlDays: parseFloat(p.DLDays) || 0 })),
  ];
  const durAvg = durRoster.length ? durRoster.reduce((s, d) => s + d.f, 0) / durRoster.length : 1;
  const durRisks = [...durRoster].sort((a, b) => a.f - b.f).slice(0, 4);

  return {
    rosteredHitters,
    starters,
    bench: {
      backupC,
      utilityIF,
      utilityOF,
      flexBat,
      platoonBat,
      extraBench: benchPlayers,
      roleNotes,   // per-role relaxation notes (null = contract met at full strength)
    },
    lineupVsRHP: {
      battingOrder: vRBattingOrder,
      bench: vRSplit.bench,
      totalLineupWAA: Math.round(lineupWAA_vR * 100) / 100,
    },
    lineupVsLHP: {
      battingOrder: vLBattingOrder,
      bench: vLSplit.bench,
      totalLineupWAA: Math.round(lineupWAA_vL * 100) / 100,
    },
    startingPitchers,
    reliefPitchers,
    totals: {
      totalHitterWAA: Math.round(totalHitterWAA * 100) / 100,
      totalSPWAA: Math.round(totalSPWAA * 100) / 100,
      totalRPWAA: Math.round(totalRPWAA * 100) / 100,
      // workload-scaled components: these are what actually feed totalPitcherWAA
      // and the win models, so Off wtd + SPeff + RPeff = the win-relevant total exactly
      totalSPWAAeff: Math.round(totalSPWAA * spWorkload * 100) / 100,
      totalRPWAAeff: Math.round(totalRPWAA * rpWorkload * 100) / 100,
      totalPitcherWAA: Math.round(totalPitcherWAA * 100) / 100,
      totalRosterWAA: Math.round(totalRosterWAA * 100) / 100,
      estimatedWins,
      lineupWAA_vR: Math.round(lineupWAA_vR * 100) / 100,
      lineupWAA_vL: Math.round(lineupWAA_vL * 100) / 100,
      weightedLineupWAA: Math.round(weightedLineupWAA * 100) / 100,
      vrShare: Math.round(TEAM_VR_SHARE * 1000) / 1000,
      estimatedWinsPyth: pythWins,
      lgRG: Math.round(lgRG * 100) / 100,
      games: G,   // season length used by every win model (B3)
      durabilityWeighted,
      excludeInjured,
    },
    // Win-model lenses — the page's model selector reads from here.
    models: {
      linearWins: estimatedWins,
      pythWins,
      runs: {
        RS: Math.round(runs.RS), RA: Math.round(runs.RA), netRD: Math.round(runs.netRD),
        RPW: Math.round(runs.RPW * 100) / 100, lgRG: Math.round(lgRG * 100) / 100,
        runDiff: Math.round(runs.RS - runs.RA),
      },
      monteCarlo,
      levers,
      callups,
      durability: { avg: durAvg, factors: durRoster, risks: durRisks },
    },
  };
}

export {
  getEligiblePositions,
  getMaxWAA,
  getPositionWAA,
  getPositionWAAForSplit,
  optimizeBattingOrder,
  selectSplitStarters,
  identifyPlatoonBat,
  optimalPositionAssignment,
  canPlaySS,
  canPlayCF,
  canPlayIF,
  canPlayOF,
  canPlayAllIF,
  canPlayCFAndCornerOF,
  WAA_COLUMNS,
  OBP_COLUMNS,
  WOBA_COLUMNS,
};

// ─── League win baseline (shared by Team Standings + Roster Optimizer) ───────────
// Every team fields its best 26, so the AVERAGE optimized roster sits well above the
// league-average player — i.e. the raw `G/2 + WAA` overstates where you'll finish.
// `leagueWinOffset` is that average winBasis (platoon lineups + pitching); subtract it
// and wins become zero-sum (total W = total L), so the two screens agree on projected
// finish. Same org set as TeamStandingsPage so the offset (and thus wins) match exactly.
const FALLBACK_MIN_ROSTER = 20;   // matches TeamStandingsPage: filter cameo foreign clubs on loan

export function leagueOrgs(hitters, pitchers, knownTeams = null) {
  const cnt = {};
  const tally = (p) => {
    const o = p.ORG;
    if (!o || o === '-' || o === '0') return;
    if (knownTeams && !knownTeams.has(o)) return;
    cnt[o] = (cnt[o] || 0) + 1;
  };
  hitters.forEach(tally); pitchers.forEach(tally);
  let orgs = Object.keys(cnt);
  if (!knownTeams) orgs = orgs.filter((o) => cnt[o] >= FALLBACK_MIN_ROSTER);
  return orgs;
}

export function leagueWinOffset(hitters, pitchers, knownTeams = null, league = null, vrShare = null) {
  const orgs = leagueOrgs(hitters, pitchers, knownTeams);
  if (!orgs.length) return 0;
  let sum = 0;
  for (const org of orgs) {
    // vrShare MUST match the basis of the roster this offset is subtracted from —
    // omitting it here while the caller's roster uses the metadata value would
    // mis-center wins by the platoon-weight difference.
    const t = optimizeRoster(hitters, pitchers, { teamOrg: org, league, vrShare }).totals;
    sum += t.weightedLineupWAA + t.totalPitcherWAA;   // raw winBasis (no offset, G-independent)
  }
  return sum / orgs.length;
}
