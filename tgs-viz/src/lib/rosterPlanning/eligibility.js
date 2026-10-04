// ============================================================================
// eligibility.js — roster state, Rule 5, options: read from data, never derived.
//
// Port of ours' rosterPlanning/eligibility.js. Ours computed:
//   - parseContractStatus: arbitration at 3 service years, FA at 6, Super Two
//     (eligibility.js:55-81) → dropped; the per-year status comes from OOTP's
//     salary report (status.js).
//   - calcR5Projection: protection 5 years if signed at 18 or under, else 4
//     (eligibility.js:104-115) → dropped; R5 is the export's `Rule5Eligible` flag.
//   - calcMLFA: MiLB free agency after 7 pro years (119-127) → dropped; unknown.
//   - getOptionsInfo: 3 options (133) → options used only; remaining unknown.
// filterR5Protect is ours' planning heuristic and is ported (thresholds in
// rosterRules.js).
// ============================================================================
import {
  isOn40Man, isActiveRoster, isOnIL, isOnIL60, isRule5Eligible, getYearsProtectedFromRule5,
  getOptionsUsed, getOptionYearUsed, hasNoTrade, getContractYearsRemaining, getPrice,
} from "../accessors.js";
import {
  FORTY_MAN_LIMIT, R5_DEFAULT_THRESHOLD, R5_PROTECT_BUFFER,
  DISPLACE_KEEP_WAR, DISPLACE_KEEP_YEARS, DISPLACE_KEEP_SALARY,
} from "./rosterRules.js";

/**
 * Roster state from the data. `on40` / `act` are tri-state in the accessors;
 * here null (unknown) reads as "not on it" for placement, and `on40Known`
 * says whether the row carried the flag at all.
 * IL: only a 40-man player's IL stint is an MLB IL stint; OnDL on a minor
 * leaguer is his minor-league IL and does not move him.
 */
export function rosterState(p) {
  const on40 = isOn40Man(p);
  const act = isActiveRoster(p);
  const il60 = on40 === true && isOnIL60(p);
  const il = on40 === true && !il60 && isOnIL(p);
  return { on40: on40 === true, on40Known: on40 !== null, act: act === true, ilShort: il, ilLong: il60 };
}

/**
 * Rule 5 from the OOTP roster export's own flag. `eligible` is tri-state
 * (null = the export did not reach this player). `exposed` = eligible and not
 * on the 40-man. WHEN a not-yet-eligible player becomes eligible is unknown:
 * the signing-age rule and the draft year it needs are not in the data.
 */
export function r5Info(p, on40) {
  const eligible = isRule5Eligible(p);
  return {
    eligible,
    yearsProtected: getYearsProtectedFromRule5(p),
    isProtected: on40 === true,
    exposed: on40 !== true && eligible === true,
  };
}

/** Options: what the export says was used. Remaining needs the option limit: unknown. */
export function optionsInfo(p) {
  return { used: getOptionsUsed(p), yearUsed: getOptionYearUsed(p), remaining: null, outOfOptions: null };
}

const scoreOf = (ep) => ep._fv ?? ep._warP ?? ep._war ?? -Infinity;

// A 40-man player is "displaceable" when dropping him for a protect is realistic:
// not a no-trade deal, not an active regular, not a big guaranteed contract.
function isDisplaceable40Man(ep) {
  if (ep._st?.on40 !== true) return false;
  if (hasNoTrade(ep) === true) return false;
  if (ep._st.act === true && (ep._war ?? 0) >= DISPLACE_KEEP_WAR) return false;
  const yearsLeft = getContractYearsRemaining(ep) ?? 0;
  const salary = getPrice(ep) ?? 0;
  if (yearsLeft >= DISPLACE_KEEP_YEARS && salary >= DISPLACE_KEEP_SALARY) return false;
  return true;
}

/**
 * Partition R5-exposed prospects into protection tiers (ours filterR5Protect).
 * Exposed = the export's Rule5Eligible flag and not on the 40-man (after moves).
 *   shortlist / others — the threshold split (worktable + slider).
 *   mustProtect / considerProtecting — slot-aware tiers for Smart Suggestions.
 */
export function filterR5Protect(rows, fvThreshold = R5_DEFAULT_THRESHOLD, opts = {}) {
  const fortyManCapacity = opts.fortyManCapacity ?? FORTY_MAN_LIMIT;
  const buffer = opts.protectBuffer ?? R5_PROTECT_BUFFER;

  const exposed = rows.filter((ep) => ep._st?.on40 !== true && !ep._r5?.isProtected && ep._r5?.eligible === true);
  const byScore = (a, b) => scoreOf(b) - scoreOf(a);
  const shortlist = exposed.filter((ep) => scoreOf(ep) >= fvThreshold).sort(byScore);
  const others = exposed.filter((ep) => scoreOf(ep) < fvThreshold).sort(byScore);

  const fortyMan = rows.filter((ep) => ep._st?.on40 === true);
  const openSlots = Math.max(0, fortyManCapacity - fortyMan.length);
  const displaceablePool = fortyMan.filter(isDisplaceable40Man).sort((a, b) => scoreOf(a) - scoreOf(b));

  const mustProtect = [];
  const considerProtecting = [];
  shortlist.forEach((ep, idx) => {
    const score = scoreOf(ep);
    if (idx < openSlots) { mustProtect.push({ player: ep, score, reason: "openSlot" }); return; }
    const floorPlayer = displaceablePool[idx - openSlots];
    if (!floorPlayer) return;
    const floorScore = scoreOf(floorPlayer);
    const entry = { player: ep, score, reason: "beatsFloor", displacedPlayer: floorPlayer, displacedScore: floorScore };
    if (score >= floorScore + buffer) mustProtect.push(entry);
    else if (score >= floorScore) considerProtecting.push(entry);
  });

  return {
    shortlist, others, mustProtect, considerProtecting,
    debug: { openSlots, fortyManCount: fortyMan.length, displaceableCount: displaceablePool.length, buffer },
  };
}
