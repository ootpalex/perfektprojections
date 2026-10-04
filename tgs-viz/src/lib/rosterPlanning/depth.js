// ============================================================================
// depth.js — active-roster and inactive 40-man coverage + the depth chart.
// Port of ours' rosterPlanning/depth.js. Same logic; roster state comes from
// the planner row's `_st` (eligibility.rosterState + moves) instead of
// `meta.act` / `meta.on40`, positions from accessors. Thresholds are ours'
// advice (rosterRules.js §2), not OOTP rules.
// ============================================================================
import { getSpWar, getRpWar, getSpWarP, getRpWarP, isEligible, isCurrentlyEligible, getPos, isStarter } from "../accessors.js";
import {
  COVERAGE_POSITIONS, ACTIVE_COVER_NEED, ACTIVE_COVER_IDEAL, ROTATION_SLOTS,
  ACTIVE_PITCHERS_MAX, ACTIVE_PITCHERS_MIN, NEAR_FULL_ACTIVE,
  INACTIVE_TILE_NEEDS, INACTIVE_SP_SLOTS, FORTY_BALANCE_MAX,
} from "./rosterRules.js";

const isPitcherRow = (ep) => ep._type === "pitcher";
// SP-role = the Starter flag (his rows carry no separate 'Starter P').
export const isSpRole = (ep) => isStarter(ep);

/**
 * Top `spSlots` SP-role pitchers by SP WAR fill the rotation; every other
 * pitcher is bullpen. Rows come back role-locked (_war / _warP / _fv).
 */
export function classifyPitchers(pitchers, spSlots) {
  const sp = [...pitchers]
    .filter((p) => isSpRole(p) && getSpWar(p) != null)
    .sort((a, b) => (getSpWar(b) ?? -999) - (getSpWar(a) ?? -999))
    .slice(0, spSlots)
    .map((p) => ({ ...p, _war: p._sp?.war ?? getSpWar(p), _warP: p._sp?.warP ?? getSpWarP(p), _fv: p._sp?.fv ?? p._fv }));
  const taken = new Set(sp.map((p) => p._uid));
  const rp = pitchers
    .filter((p) => !taken.has(p._uid))
    .sort((a, b) => (getRpWar(b) ?? -999) - (getRpWar(a) ?? -999))
    .map((p) => ({ ...p, _war: p._rp?.war ?? getRpWar(p), _warP: p._rp?.warP ?? getRpWarP(p), _fv: p._rp?.fv ?? p._fv }));
  return { sp, rp };
}

function positionCover(hitters, positions) {
  const coverage = {}, coveragePotential = {}, coverageUids = {}, coverageUidsPotential = {};
  positions.forEach((pos) => {
    const current = hitters.filter((ep) => isCurrentlyEligible(ep, pos));
    const potentialOnly = hitters.filter((ep) => isEligible(ep, pos) && !isCurrentlyEligible(ep, pos));
    coverage[pos] = current.length;
    coveragePotential[pos] = potentialOnly.length;
    coverageUids[pos] = new Set(current.map((ep) => ep._uid));
    coverageUidsPotential[pos] = new Set(potentialOnly.map((ep) => ep._uid));
  });
  return { coverage, coveragePotential, coverageUids, coverageUidsPotential };
}

function pitcherUids(pitchers, cov) {
  cov.coverageUids.SP = new Set(pitchers.filter(isSpRole).map((ep) => ep._uid));
  cov.coverageUids.RP = new Set(pitchers.filter((p) => !isSpRole(p)).map((ep) => ep._uid));
  cov.coverageUidsPotential.SP = new Set();
  cov.coverageUidsPotential.RP = new Set();
}

export function analyzeActiveCoverage(active) {
  const hitters = active.filter((ep) => !isPitcherRow(ep));
  const pitchers = active.filter(isPitcherRow);
  const cov = positionCover(hitters, COVERAGE_POSITIONS);
  const { sp: spList, rp: rpList } = classifyPitchers(pitchers, ROTATION_SLOTS);
  pitcherUids(pitchers, cov);

  const warnings = [];
  const c = cov.coverage;
  if (c.C < ACTIVE_COVER_NEED) {
    warnings.push({ type: "coverage", pos: "C", severity: "error",
      message: `Only ${c.C} C-eligible player${c.C === 1 ? "" : "s"} on the active roster; need ${ACTIVE_COVER_NEED} (starter + backup).` });
  }
  COVERAGE_POSITIONS.filter((p) => p !== "C").forEach((pos) => {
    if (c[pos] < ACTIVE_COVER_NEED) {
      warnings.push({ type: "coverage", pos, severity: "error",
        message: `No injury backup at ${pos}: only ${c[pos]} eligible player on the active roster.` });
    } else if (c[pos] < ACTIVE_COVER_IDEAL) {
      warnings.push({ type: "coverage", pos, severity: "info",
        message: `${pos} cover is minimal (${c[pos]} eligible): a double injury leaves the position exposed.` });
    }
  });
  if (pitchers.length > ACTIVE_PITCHERS_MAX) {
    warnings.push({ type: "balance", severity: "error",
      message: `Active roster is over-pitched: ${pitchers.length} pitchers / ${hitters.length} hitters.` });
  } else if (pitchers.length < ACTIVE_PITCHERS_MIN && hitters.length + pitchers.length >= NEAR_FULL_ACTIVE) {
    warnings.push({ type: "balance", severity: "error", message: `Active roster is under-pitched: only ${pitchers.length} pitchers.` });
  }
  if (spList.length < ROTATION_SLOTS) {
    warnings.push({ type: "role", severity: "error",
      message: `Only ${spList.length} SP-role pitcher${spList.length === 1 ? "" : "s"} on the active roster; a rotation needs ${ROTATION_SLOTS}.` });
  }
  return {
    ...cov, hitterCount: hitters.length, pitcherCount: pitchers.length,
    spCount: spList.length, rpCount: rpList.length, spList, rpList, warnings,
  };
}

const INACTIVE_TILE_POSITIONS = ["C", "SS", "CF"];

export function analyzeInactiveCoverage(inactive40) {
  const hitters = inactive40.filter((ep) => !isPitcherRow(ep));
  const pitchers = inactive40.filter(isPitcherRow);
  const cov = positionCover(hitters, INACTIVE_TILE_POSITIONS);
  const { sp: spList, rp: rpList } = classifyPitchers(pitchers, INACTIVE_SP_SLOTS);
  cov.coverage.SP = spList.length;
  cov.coverage.RP = rpList.length;
  cov.coveragePotential.SP = 0;
  cov.coveragePotential.RP = 0;
  pitcherUids(pitchers, cov);

  const warnings = [];
  Object.entries(INACTIVE_TILE_NEEDS).forEach(([pos, need]) => {
    if (cov.coverage[pos] < need) {
      warnings.push({ type: "depth", pos, severity: "error",
        message: `Inactive 40-man lacks ${pos} depth: have ${cov.coverage[pos]}, need ${need}.` });
    }
  });
  return { ...cov, spList, rpList, hitterCount: hitters.length, pitcherCount: pitchers.length, warnings, requirements: INACTIVE_TILE_NEEDS };
}

/** The depth chart for planner rows (each carrying `_st`). */
export function buildDepthChart(rows) {
  const onIl = (ep) => ep._st.ilShort || ep._st.ilLong;
  const active = rows.filter((ep) => ep._st.act && ep._st.on40 && !onIl(ep));
  const inactive40 = rows.filter((ep) => ep._st.on40 && !ep._st.act && !onIl(ep));
  const ilShort = rows.filter((ep) => ep._st.ilShort);
  const ilLong = rows.filter((ep) => ep._st.ilLong);
  const sortByWar = (a, b) => (b._war ?? -999) - (a._war ?? -999);

  const coverage = analyzeActiveCoverage(active);
  const inactiveCoverage = analyzeInactiveCoverage(inactive40);

  const buildSlots = (players, cr) => {
    const taken = new Set();
    const pick = (fn) => {
      const out = players.filter((ep) => !isPitcherRow(ep) && !taken.has(ep._uid) && fn(ep)).sort(sortByWar);
      out.forEach((ep) => taken.add(ep._uid));
      return out;
    };
    const C = pick((ep) => getPos(ep) === "C" || isEligible(ep, "C"));
    const IF = pick((ep) => ["1B", "2B", "3B", "SS"].includes(getPos(ep)));
    const OF = pick((ep) => ["LF", "CF", "RF"].includes(getPos(ep)));
    const DH = pick((ep) => getPos(ep) === "DH");
    const bench = pick(() => true);
    return { C, IF, OF, DH, bench, SP: [...cr.spList].sort(sortByWar), RP: [...cr.rpList].sort(sortByWar) };
  };

  const fortyRows = [...active, ...inactive40];
  const fortyHitters = fortyRows.filter((ep) => !isPitcherRow(ep)).length;
  const fortyPitchers = fortyRows.filter(isPitcherRow).length;
  const balanceWarnings = [];
  if (fortyPitchers > FORTY_BALANCE_MAX) {
    balanceWarnings.push({ type: "balance", severity: "info", message: `40-man is pitcher-heavy: ${fortyPitchers} pitchers / ${fortyHitters} hitters.` });
  } else if (fortyHitters > FORTY_BALANCE_MAX) {
    balanceWarnings.push({ type: "balance", severity: "info", message: `40-man is hitter-heavy: ${fortyHitters} hitters / ${fortyPitchers} pitchers.` });
  }

  return {
    activeSlots: buildSlots(active, coverage),
    inactiveSlots: buildSlots(inactive40, inactiveCoverage),
    ilShort, ilLong, coverage, inactiveCoverage,
    warnings: [...coverage.warnings, ...inactiveCoverage.warnings, ...balanceWarnings],
    counts: { active: active.length, inactive40: inactive40.length, fortyHitters, fortyPitchers, ilShort: ilShort.length, ilLong: ilLong.length },
  };
}
