// ============================================================================
// prospectTiers.js — the prospect board's pool, FV tiers and farm rankings,
// ported from ootp-dashboard ("ours": app/src/utils/prospects.js and the tier
// constants in app/src/utils/constants.js).
//
// What changed from ours (docs/phase4/views.md):
//   - The value a prospect is tiered on is no longer ours' v21 FV
//     (cur + gap × creditAge with the hand-tuned gapMax/gapExp curve). That
//     curve is dropped. The input is his FV engine's projected peak
//     (usePlayersWithFV `_potentialWAA`, "Proj Pot"): the ML model's gain when
//     dev_ml.json is loaded and on the same pull, else the DEV cell gain, else
//     the measured DEV curve, else his assumed model. `_potentialSource` says
//     which, per row.
//   - Units are his display basis, WAA (value vs average), not ours' WAR. WAR
//     columns are absent on BLM/TGS/RG until their next pull; WAA is on every row.
//   - Player reads go through lib/accessors.js.
// The tier machinery itself (suggestThresholds, assignFVTier, the farm
// rankings and scouting report) is ours, verbatim apart from those reads.
// ============================================================================
import {
  num, getOrg, getLevel, isAmateur, isFreeAgent, isOn40Man, getMlbServiceDays, getPlayerType,
} from './accessors.js';

// ── FV tiers (ours constants.js; 🟡 ours' constants) ────────────────────────
// Default $M per tier were set on ours' boards. The tiers are cut by rank
// (FanGraphs tier populations scaled to the league's team count), so the
// per-tier $ stays meaningful whatever unit the FV input is in.
export const FV_TIERS = [
  { id: '80', label: '80', defaultBat: 162, defaultPit: 120 },
  { id: '70', label: '70', defaultBat: 112, defaultPit: 85 },
  { id: '65', label: '65', defaultBat: 62, defaultPit: 64 },
  { id: '60', label: '60', defaultBat: 55, defaultPit: 60 },
  { id: '55', label: '55', defaultBat: 46, defaultPit: 34 },
  { id: '50', label: '50', defaultBat: 28, defaultPit: 21 },
  { id: '45+', label: '45+', defaultBat: 8, defaultPit: 6 },
  { id: '45', label: '45', defaultBat: 6, defaultPit: 4 },
  { id: '40+', label: '40+', defaultBat: 4, defaultPit: 3 },
  { id: '40', label: '40', defaultBat: 2, defaultPit: 1 },
  { id: '35+', label: '35+', defaultBat: 1, defaultPit: 0.5 },
];

// FanGraphs per-30-team tier populations (mean, sd). 🟡 ours' constants.
export const FG_TIER_STATS = {
  '80': { avg: 0.214, std: 0.426 },
  '70': { avg: 0.571, std: 0.629 },
  '65': { avg: 1.571, std: 1.351 },
  '60': { avg: 12.071, std: 4.006 },
  '55': { avg: 21.214, std: 4.130 },
  '50': { avg: 76.714, std: 9.202 },
  '45+': { avg: 39.714, std: 4.909 },
  '45': { avg: 126.357, std: 10.356 },
  '40+': { avg: 171.857, std: 25.798 },
  '40': { avg: 395.643, std: 27.873 },
  '35+': { avg: 372.643, std: 51.713 },
};

// Tier-threshold search parameters (ours V5c). 🟡 ours' constants, calibrated
// on ours' SSB + BLM-MIA data.
export const TIER_SEARCH_K = 1.0;
export const TIER_SNAP_T_THRESH = 1.20;
export const TIER_SNAP_WINDOW = 7;

export const defaultDollarValues = () => {
  const dv = {};
  FV_TIERS.forEach((t) => { dv[t.id] = { bat: t.defaultBat, pit: t.defaultPit }; });
  return dv;
};

// ── who is a prospect ──────────────────────────────────────────────────────
// Ours' definition, not an OOTP rule: fewer than 45 days of MLB service (a
// missing figure counts as none). Kept as ours had it; OOTP's own rookie flag
// (RookieStatus, isRookie) is on SSB's export rows only.
export const PROSPECT_MAX_MLB_DAYS = 45;
export const isProspect = (p) => {
  const mld = getMlbServiceDays(p);
  return mld == null || mld < PROSPECT_MAX_MLB_DAYS;
};
// In an organisation: ours excluded rows tagged as draft / IAFA signings by
// meta.source. His rows carry Lev 'AMA' (draft pool) and FA instead.
export const isInOrg = (p) => getOrg(p) !== '-' && !isAmateur(p) && !isFreeAgent(p);
export const isOrgProspect = (p) => isInOrg(p) && isProspect(p);

// Big-league squad for the "MLB players at or above this tier" count. Ours:
// Lev MLB and on the 40-man. Where the 40-man flag is unknown (BLM, or an SSB
// row outside the roster export) the level alone decides.
export const isMlbSquad = (p) => getLevel(p) === 'MLB' && isOn40Man(p) !== false;

// ── his FV engine's fields (usePlayersWithFV) ──────────────────────────────
// Computed fields stamped by his hook, not raw columns.
export const fvProjPeak = (p) => num(p?._potentialWAA);     // "Proj Pot", display WAA
export const fvCurrent = (p) => num(p?._currentWAA);         // current, display WAA
export const fvListedPot = (p) => num(p?._rawPotentialWAA);  // listed potential, display WAA
export const fvSource = (p) => p?._potentialSource ?? null;  // 'ML' | 'DEV cell' | 'measured curve' | 'model'
// The role his engine prices the peak on ('hitter' | 'sp' | 'rp'), and that
// role's replacement offset (WAR = WAA + offset, leagueCalib).
export const fvRole = (p) => p?._fvBreakdown?.potentialRole ?? null;
export const fvReplOffset = (p) => num(p?._fvBreakdown?.potentialOffsetUsed);

// One pool entry per FV-enriched row: ours' field names (_fv, _baseVal,
// _currentVal, _poolType), his values.
export function buildProspectPool(fvRows) {
  return fvRows.map((p) => {
    const type = getPlayerType(p);
    const role = fvRole(p);
    return {
      ...p,
      _fv: fvProjPeak(p),
      _baseVal: fvListedPot(p) ?? 0,
      _currentVal: fvCurrent(p),
      _fvSource: fvSource(p),
      _role: type === 'pitcher' ? (role === 'rp' ? 'rp' : 'sp') : null,
      _poolType: type,
    };
  });
}

const fvOf = (p) => p._fv ?? p._baseVal ?? 0;

// ── tier thresholds (ours V5c, verbatim) ───────────────────────────────────
function _sd(arr) {
  if (arr.length < 2) return 0;
  const m = arr.reduce((s, v) => s + v, 0) / arr.length;
  return Math.sqrt(arr.reduce((s, x) => s + (x - m) ** 2, 0) / (arr.length - 1));
}

function _welchT(a, b) {
  if (a.length < 2 || b.length < 2) return null;
  const ma = a.reduce((s, v) => s + v, 0) / a.length;
  const mb = b.reduce((s, v) => s + v, 0) / b.length;
  const va = a.reduce((s, v) => s + (v - ma) ** 2, 0) / (a.length - 1);
  const vb = b.reduce((s, v) => s + (v - mb) ** 2, 0) / (b.length - 1);
  const se = Math.sqrt(va / a.length + vb / b.length);
  if (!isFinite(se) || se === 0) return null;
  return (ma - mb) / se;
}

// For each tier (top down) search the rank window [cum_μ ± K·cum_σ] for the
// best natural break (FV-gap z or potential-cluster Welch t); snap when
// significant, else round(cum_μ). Then turn each tier's break into an FV cut.
export function suggestThresholds(prospects, numTeams) {
  if (!prospects || prospects.length === 0) return {};
  const sorted = [...prospects].sort((a, b) => fvOf(b) - fvOf(a));
  const N = sorted.length;
  const scale = numTeams / 30;
  const thresholds = {};
  const potOf = (p) => p._baseVal ?? p.pot ?? 0;
  // Changed from ours: a pool smaller than the FanGraphs cumulative population
  // puts a break at N, where ours read sorted[N] (undefined) and threw. The
  // missing neighbour below the last player is read as the last player.
  const fvAt = (i) => fvOf(sorted[Math.min(i, N - 1)]);

  const tierStates = [];
  let cumMu = 0;
  let cumVar = 0;
  let prevI = 0;
  for (const tier of FV_TIERS) {
    const stats = FG_TIER_STATS[tier.id];
    if (!stats) continue;
    const mu = stats.avg * scale;
    const sg = stats.std * scale;
    cumMu += mu;
    cumVar += sg * sg;
    const cumSig = Math.sqrt(cumVar);

    const defaultI = Math.max(prevI, Math.min(N, Math.round(cumMu)));
    const rLo = Math.max(prevI, Math.floor(cumMu - TIER_SEARCH_K * cumSig));
    const rHi = Math.min(N, Math.ceil(cumMu + TIER_SEARCH_K * cumSig));

    let bestI = defaultI;
    let bestScore = -Infinity;

    if (rHi > rLo) {
      const ctxLo = Math.max(0, rLo - TIER_SNAP_WINDOW);
      const ctxHi = Math.min(N, rHi + TIER_SNAP_WINDOW);
      const ctxFVs = sorted.slice(ctxLo, ctxHi).map(fvOf);
      const fvScale = Math.max(0.05, _sd(ctxFVs));

      for (let i = rLo; i <= rHi && i < N; i++) {
        if (i <= prevI) continue;
        const fvGap = fvOf(sorted[i - 1]) - fvOf(sorted[i]);
        const zFV = fvGap / fvScale;
        const wLo = Math.max(prevI, i - TIER_SNAP_WINDOW);
        const wHi = Math.min(N, i + TIER_SNAP_WINDOW);
        const above = sorted.slice(wLo, i).map(potOf);
        const below = sorted.slice(i, wHi).map(potOf);
        const zPot = _welchT(above, below) ?? 0;
        const score = Math.max(zFV, zPot);
        if (score > bestScore) {
          bestScore = score;
          bestI = i;
        }
      }
      if (bestScore < TIER_SNAP_T_THRESH) bestI = defaultI;
    }
    tierStates.push({ id: tier.id, bestI, prevI, cumMu });
    prevI = bestI;
  }

  const POP_STABLE = 5;
  const ALPHA = 0.5;

  const allAnchors = [];
  const stableAnchors = [];
  for (const ts of tierStates) {
    if (ts.bestI > ts.prevI) {
      const cutFV = (fvAt(ts.bestI - 1) + fvAt(ts.bestI)) / 2;
      const anchor = { cumMu: ts.cumMu, cutFV };
      allAnchors.push(anchor);
      if (ts.bestI - ts.prevI >= POP_STABLE) stableAnchors.push(anchor);
    }
  }

  const fitLogLinear = (anchorList) => {
    if (anchorList.length < 2) return null;
    const xs = anchorList.map((a) => Math.log(a.cumMu));
    const ys = anchorList.map((a) => a.cutFV);
    const n = anchorList.length;
    const mx = xs.reduce((s, v) => s + v, 0) / n;
    const my = ys.reduce((s, v) => s + v, 0) / n;
    let nm = 0, den = 0;
    for (let i = 0; i < n; i++) {
      nm += (xs[i] - mx) * (ys[i] - my);
      den += (xs[i] - mx) ** 2;
    }
    if (den === 0) return null;
    const slope = nm / den;
    return { slope, intercept: my - slope * mx };
  };
  const fitStable = fitLogLinear(stableAnchors);
  const fitAll = fitLogLinear(allAnchors);
  const evalFit = (fit, cumMuT) => fit.slope * Math.log(cumMuT) + fit.intercept;

  const topFV = N > 0 ? fvOf(sorted[0]) : 0;
  const minAnchorCumMu = allAnchors.length > 0 ? Math.min(...allAnchors.map((a) => a.cumMu)) : Infinity;

  for (const ts of tierStates) {
    const pop = ts.bestI - ts.prevI;
    let cut;
    if (pop >= POP_STABLE) {
      cut = (fvAt(ts.bestI - 1) + fvAt(ts.bestI)) / 2;
    } else if (pop >= 1) {
      const midpoint = (fvAt(ts.bestI - 1) + fvAt(ts.bestI)) / 2;
      const lowestPlayerFV = fvOf(sorted[ts.bestI - 1]);
      if (fitStable != null) {
        const lrPred = evalFit(fitStable, ts.cumMu);
        const blend = midpoint + ALPHA * (lrPred - midpoint);
        const candidate = Math.max(midpoint, blend);
        cut = candidate <= lowestPlayerFV ? candidate : midpoint;
      } else {
        cut = midpoint;
      }
    } else {
      const isTopmost = ts.cumMu < minAnchorCumMu;
      if (isTopmost && fitStable != null) {
        const lrPred = evalFit(fitStable, ts.cumMu);
        cut = topFV + ALPHA * (lrPred - topFV);
      } else if (fitAll != null) {
        cut = evalFit(fitAll, ts.cumMu);
      } else if (allAnchors.length === 1) {
        cut = allAnchors[0].cutFV;
      } else {
        cut = topFV + 0.01;
      }
    }
    thresholds[ts.id] = Math.round(cut * 100) / 100;
  }
  return thresholds;
}

export function assignFVTier(fv, thresholds) {
  if (fv == null) return null;
  for (const tier of FV_TIERS) {
    if (fv >= (thresholds[tier.id] ?? Infinity)) return tier.id;
  }
  return null;
}

export function getDollarValue(tierId, playerType, dollarValues) {
  const dv = dollarValues[tierId];
  if (!dv) return 0;
  return playerType === 'pitcher' ? (dv.pit ?? 0) : (dv.bat ?? 0);
}

// Per-tier counts and FV range for the configuration table (ours' tierStats memo).
export function tierStats(prospectPool, thresholds) {
  const stats = {};
  let cumulative = 0;
  FV_TIERS.forEach((tier) => {
    const inTier = prospectPool.filter((p) => assignFVTier(fvOf(p), thresholds) === tier.id);
    cumulative += inTier.length;
    const fvs = inTier.map(fvOf);
    stats[tier.id] = {
      count: inTier.length, cumulative,
      hit: inTier.filter((p) => p._poolType === 'hitter').length,
      pit: inTier.filter((p) => p._poolType === 'pitcher').length,
      minFV: fvs.length ? Math.min(...fvs) : null,
      maxFV: fvs.length ? Math.max(...fvs) : null,
    };
  });
  return stats;
}

// Tiered, ranked board (ours' rankedPool memo): players below the last tier
// drop off; overall and per-org rank by FV, independent of the filters.
export function rankPool(prospectPool, thresholds, dollarValues) {
  const withTiers = prospectPool.map((p) => {
    const tierId = assignFVTier(fvOf(p), thresholds);
    const dollarVal = tierId ? getDollarValue(tierId, p._poolType, dollarValues) : 0;
    return { ...p, _tierId: tierId, _dollarVal: dollarVal };
  }).filter((p) => p._tierId != null);
  withTiers.sort((a, b) => fvOf(b) - fvOf(a));
  withTiers.forEach((p, i) => { p._overallRank = i + 1; });
  const orgCounters = {};
  withTiers.forEach((p) => {
    const org = getOrg(p);
    orgCounters[org] = (orgCounters[org] || 0) + 1;
    p._orgRank = orgCounters[org];
  });
  return withTiers;
}

// Number of values at or above `threshold` in a descending array (binary search).
export function countAtOrAbove(descValues, threshold) {
  if (threshold == null) return null;
  let lo = 0, hi = descValues.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (descValues[mid] >= threshold) lo = mid + 1; else hi = mid;
  }
  return lo;
}

// ── farm rankings (ours, verbatim apart from the org read) ─────────────────
export function buildScoutingReport(ceiling, floor, batting, pitching) {
  const parts = [];
  const avg = (ceiling + floor) / 2;
  if (avg >= 60) parts.push('Premier System');
  else if (avg >= 55) parts.push('Strong System');
  else if (avg >= 45) parts.push('Average System');
  else if (avg >= 35) parts.push('Weak System');
  else parts.push('Barren System');
  if (ceiling >= 70) parts.push('Headline Talent');
  else if (ceiling >= 60) parts.push('Impact Talent');
  if (floor >= 70) parts.push('Endless Depth');
  else if (floor >= 60) parts.push('Stockpiled Depth');
  else if (floor <= 35) parts.push('Empty Shelf');
  if (ceiling >= floor + 10 && floor < 50) parts.push('Top Heavy');
  else if (floor >= ceiling + 10 && ceiling < 50) parts.push('Low Ceiling');
  if (avg >= 35) {
    if (Math.abs(batting - pitching) <= 5 && avg >= 45) parts.push('Balanced');
    else if (batting >= pitching + 10) parts.push('Bat Heavy');
    else if (pitching >= batting + 10) parts.push('Arm Heavy');
  }
  return parts.join(' | ');
}

export function calcFarmRankings(prospectPool, thresholds, dollarValues, teams) {
  const byTeam = {};
  teams.forEach((t) => { byTeam[t] = []; });
  prospectPool.forEach((p) => {
    const org = getOrg(p);
    if (org !== '-') {
      if (!byTeam[org]) byTeam[org] = [];
      byTeam[org].push(p);
    }
  });

  const rankings = [];
  Object.entries(byTeam).forEach(([team, players]) => {
    const tierCounts = {};
    FV_TIERS.forEach((t) => { tierCounts[t.id] = 0; });
    let totalValue = 0;
    let hitValue = 0, pitValue = 0;
    let count50Plus = 0, count40Plus = 0;
    players.forEach((p) => {
      const tierId = assignFVTier(fvOf(p), thresholds);
      if (!tierId) return;
      tierCounts[tierId] = (tierCounts[tierId] || 0) + 1;
      const dv = getDollarValue(tierId, p._poolType, dollarValues);
      totalValue += dv;
      if (p._poolType === 'pitcher') pitValue += dv;
      else hitValue += dv;
      const tierIdx = FV_TIERS.findIndex((t) => t.id === tierId);
      if (tierIdx >= 0 && tierIdx <= 5) count50Plus++;
      if (tierIdx >= 0 && tierIdx <= 8) count40Plus++;
    });
    const tieredCount = Object.values(tierCounts).reduce((a, b) => a + b, 0);
    rankings.push({ team, totalValue, hitValue, pitValue, count50Plus, count40Plus, tierCounts, count: tieredCount });
  });

  const zScore = (vals) => {
    const n = vals.length;
    if (n < 2) return vals.map(() => 0);
    const mean = vals.reduce((a, b) => a + b, 0) / n;
    const std = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / n) || 1;
    return vals.map((v) => (v - mean) / std);
  };

  const ceilVals = rankings.map((r) => {
    let val = 0;
    FV_TIERS.slice(0, 6).forEach((t) => {
      val += (r.tierCounts[t.id] || 0) * ((dollarValues[t.id]?.bat ?? 0) + (dollarValues[t.id]?.pit ?? 0)) / 2;
    });
    return val;
  });
  const ceilZ = zScore(ceilVals);
  const floorZ = zScore(rankings.map((r) => r.count40Plus));
  const batZ = zScore(rankings.map((r) => r.hitValue));
  const pitZ = zScore(rankings.map((r) => r.pitValue));

  rankings.forEach((r, i) => {
    r.ceiling = Math.round(50 + 10 * ceilZ[i]);
    r.floor = Math.round(50 + 10 * floorZ[i]);
    r.batting = Math.round(50 + 10 * batZ[i]);
    r.pitching = Math.round(50 + 10 * pitZ[i]);
    r.report = buildScoutingReport(r.ceiling, r.floor, r.batting, r.pitching);
    r.avgValue = r.count > 0 ? r.totalValue / r.count : 0;
  });

  rankings.sort((a, b) => b.totalValue - a.totalValue);
  rankings.forEach((r, i) => { r.rank = i + 1; });
  return rankings;
}

// Per-league saved board settings. Ours kept { thresholds, dollarValues } under
// prospect_board_settings::<slug>; the FV unit changed (WAA, his engine), so a
// new key keeps ours' WAR-unit thresholds from loading here.
export const PROSPECT_SETTINGS_KEY = 'ns-prospect-board-v1';
export const prospectSettingsKey = (league) => `${PROSPECT_SETTINGS_KEY}::${league || 'default'}`;
