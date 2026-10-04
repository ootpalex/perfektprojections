/**
 * waivers.js — waiver / DFA claim board.
 *
 * Every roster row already ships `OnWaivers` and `DFA`; nothing surfaced them,
 * so free talent passed by unnoticed. This module answers the only question a
 * claim actually poses: is this man worth a roster spot to US?
 *
 * VALUE BASIS — ORG replacement ("next man up"), leagueCalib.replacementOrg.
 * A claim is an INTERNAL cut/keep decision: the alternative to claiming him is
 * the body already holding the spot, not what the open market sells. That is
 * precisely the question replacementOrg was measured for (see leagueCalib.js
 * header), so `vor` = role WAA + the measured org offset for that role. The
 * market offsets (the $ currency) are deliberately NOT used here.
 *
 * DISPLAY stays WAA — `waa` is the raw value-vs-average the boards show; `vor`
 * is labelled as value above ORG replacement wherever it appears, never as WAA.
 *
 * ROSTER FIT is measured against the claiming org's OWN players: the weakest
 * MLB-level body in the same role bucket is the man he would push off. No
 * 40-man logic: the data carries no 40-man flag, so this module never counts
 * roster spots it cannot see.
 *
 * Everything numeric here comes from the league's own shipped rows or from the
 * measured per-league offsets — there are no constants in this file.
 */

import { replacementOrgOffset } from './leagueCalib.js';
import { getEligiblePositions } from './rosterOptimizer.js';
import { contractAAV } from './marketValue.js';
import {
  isOnWaivers as accIsOnWaivers, isDFA as accIsDFA,
  getWaiverDaysLeft, getWaiverDays, isOn40Man, getOrg,
} from './accessors.js';

const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

// StatsPlus writes these as real booleans, but the same fields arrive as 'Yes'
// strings from other exports — accept both, the way isInjured does.
function isFlag(v) {
  return v === true || v === 'true' || v === 'True' || v === 'TRUE' || v === 'Yes';
}

// Same flag rule as isFlag, read through the Phase 4 accessor adapter.
export function isOnWaivers(p) { return accIsOnWaivers(p); }
export function isDFA(p) { return accIsDFA(p); }

/**
 * The live claim clock (StatsPlus /players `days_on_waivers_left`, shipped as
 * `WaiverDaysLeft`; `WaiverDays` is the days already served). Ported from
 * ootp-dashboard app/src/utils/waivers.js.
 *
 *   'claimable' — on waivers with days left, or on waivers with no clock in the
 *                 row (a league whose pull predates the field): the flag says he
 *                 is on waivers and nothing says otherwise.
 *   'cleared'   — on waivers with 0 days left: unclaimed, can no longer be
 *                 claimed. StatsPlus keeps the waiver flag set after the clock runs out.
 *   'dfa'       — designated for assignment but not (yet) on waivers. The clock
 *                 reads 0 here because it never started, so it says nothing.
 *   null        — neither flag.
 */
export const CLOCK_CLAIMABLE = 'claimable';
export const CLOCK_CLEARED = 'cleared';
export const CLOCK_DFA = 'dfa';

export function waiverClock(p) {
  if (isOnWaivers(p)) {
    const daysLeft = getWaiverDaysLeft(p);
    return {
      state: daysLeft === 0 ? CLOCK_CLEARED : CLOCK_CLAIMABLE,
      daysLeft,
      daysOn: getWaiverDays(p),
    };
  }
  if (isDFA(p)) return { state: CLOCK_DFA, daysLeft: null, daysOn: null };
  return null;
}

/** Every player the league has made available: on waivers, DFA'd, or both. */
export function isClaimable(p) { return isOnWaivers(p) || isDFA(p); }

export function claimStatus(p) {
  if (isOnWaivers(p) && isDFA(p)) return 'DFA + Waivers';
  if (isOnWaivers(p)) return 'Waivers';
  return 'DFA';
}

const isPitcherRow = (p) => p['WAA wtd'] !== undefined || p['WAA wtd RP'] !== undefined;

/**
 * Best position a hitter can actually be used at, and his WAA there. Uses the
 * optimizer's own eligibility rule (an explicit False means OOTP says he can't
 * field there), so a claim is never priced at a position he can't play — which
 * the shipped 'Max WAA wtd' would allow.
 */
function bestHitterSpot(p) {
  let pos = null, waa = null;
  for (const cand of getEligiblePositions(p)) {
    const v = num(p[`${cand} WAA wtd`]);
    if (v !== null && (waa === null || v > waa)) { waa = v; pos = cand; }
  }
  return { pos, waa };
}

/**
 * SP or RP, decided in the SAME currency the board ranks on: the role whose
 * WAA plus its measured org offset is larger. (A swingman's spot is worth what
 * his better role is worth.)
 */
function bestPitcherSpot(p, league) {
  const sp = num(p['WAA wtd']);
  const rp = num(p['WAA wtd RP']);
  const spV = sp === null ? null : sp + replacementOrgOffset(league, 'sp');
  const rpV = rp === null ? null : rp + replacementOrgOffset(league, 'rp');
  if (spV === null && rpV === null) return { role: null, pos: p.POS || null, waa: null, vor: null };
  // `role` is the VALUE bucket we score him in, not a claim about where he plays:
  // 'WAA wtd' and 'WAA wtd RP' are quoted over different workloads, so the org
  // offsets are what make them comparable. `pos` stays whatever OOTP lists him as.
  const useRP = spV === null || (rpV !== null && rpV > spV);
  return useRP
    ? { role: 'rp', pos: p.POS || 'RP', waa: rp, vor: rpV }
    : { role: 'sp', pos: p.POS || 'SP', waa: sp, vor: spV };
}

/**
 * Score one player as a claim. `league` keys the measured org replacement
 * offsets — pass the app's league id (the same one the pages carry), never a
 * value derived from another league.
 */
export function evaluateClaim(p, league) {
  const pitcher = isPitcherRow(p);
  let role, pos, waa, vor;
  if (pitcher) {
    ({ role, pos, waa, vor } = bestPitcherSpot(p, league));
  } else {
    const spot = bestHitterSpot(p);
    role = 'hitter';
    pos = spot.pos;
    waa = spot.waa;
    vor = spot.waa === null ? null : spot.waa + replacementOrgOffset(league, 'hitter');
  }
  const clock = waiverClock(p);
  return {
    player: p,
    id: p.ID ?? p.Name,
    name: p.Name,
    org: p.ORG || null,
    level: p.Lev || null,
    age: num(p.Age),
    listedPos: p.POS || null,
    pos,
    role,
    isPitcher: pitcher,
    status: claimStatus(p),
    onWaivers: isOnWaivers(p),
    dfa: isDFA(p),
    onDL: isFlag(p.OnDL) || isFlag(p.OnDL60),
    waa,                                   // display currency (vs average)
    vor,                                   // value above ORG replacement
    salary: contractAAV(p),                // null when the row carries no deal
    contractYr: num(p.ContractYr),
    contractYrs: num(p.ContractYrs),
    svcYears: num(p.MLBSvcYrs),
    clock: clock ? clock.state : null,     // claimable / cleared / dfa (see waiverClock)
    daysLeft: clock ? clock.daysLeft : null,
    daysOn: clock ? clock.daysOn : null,
  };
}

/**
 * The man a claim would push off THIS org's active roster: the weakest
 * MLB-level player in the same role bucket. Players who are themselves on
 * waivers or DFA'd are excluded — they are already leaving, so they are not
 * the alternative to the claim.
 */
function weakestIncumbent(entries, role) {
  let worst = null;
  for (const e of entries) {
    if (e.role !== role || e.waa === null) continue;
    if (!worst || e.waa < worst.waa) worst = e;
  }
  return worst;
}

/**
 * Build the claim board for ONE league.
 *
 * @param {Array} hitters  that league's hitter rows
 * @param {Array} pitchers that league's pitcher rows
 * @param {{league: string, org?: string}} opts
 * @returns {{ entries, live, cleared, counts, offsets, incumbents }}
 *   entries    — every flagged player, best first by value above org replacement,
 *                each carrying `fit` when an org was given
 *   live       — the entries that can still be claimed (clock running, or DFA)
 *   cleared    — the entries whose claim clock has run out (see waiverClock)
 *   counts     — how many are on waivers / DFA'd / both, and the role split
 *   offsets    — the measured org replacement offsets used, for labelling
 *   incumbents — the weakest MLB body per role in the selected org
 */
export function buildClaimBoard(hitters = [], pitchers = [], { league, org } = {}) {
  const rows = [...hitters, ...pitchers];
  const claimable = rows.filter(isClaimable);
  const entries = claimable
    .map(p => evaluateClaim(p, league))
    .sort((a, b) => (b.vor ?? -Infinity) - (a.vor ?? -Infinity));

  const counts = {
    total: entries.length,
    waivers: entries.filter(e => e.onWaivers).length,
    dfa: entries.filter(e => e.dfa).length,
    both: entries.filter(e => e.onWaivers && e.dfa).length,
    hitters: entries.filter(e => e.role === 'hitter').length,
    sp: entries.filter(e => e.role === 'sp').length,
    rp: entries.filter(e => e.role === 'rp').length,
    claimable: entries.filter(e => e.clock === CLOCK_CLAIMABLE).length,
    cleared: entries.filter(e => e.clock === CLOCK_CLEARED).length,
    dfaOnly: entries.filter(e => e.clock === CLOCK_DFA).length,
    // on waivers and the row carries the clock (false on a pre-clock pull)
    clockKnown: entries.filter(e => e.onWaivers && e.daysLeft !== null).length,
  };
  const live = entries.filter(e => e.clock !== CLOCK_CLEARED);
  const cleared = entries.filter(e => e.clock === CLOCK_CLEARED);

  const offsets = {
    hitter: replacementOrgOffset(league, 'hitter'),
    sp: replacementOrgOffset(league, 'sp'),
    rp: replacementOrgOffset(league, 'rp'),
  };

  let incumbents = null;
  if (org) {
    const roster = rows
      .filter(p => p.ORG === org && p.Lev === 'MLB' && !isClaimable(p))
      .map(p => evaluateClaim(p, league));
    incumbents = {
      hitter: weakestIncumbent(roster, 'hitter'),
      sp: weakestIncumbent(roster, 'sp'),
      rp: weakestIncumbent(roster, 'rp'),
    };
    for (const e of entries) {
      const inc = e.role ? incumbents[e.role] : null;
      // Own DFA'd players are already ours — there is nothing to claim, and
      // pricing them against our own bench would be a made-up comparison.
      e.ownOrg = !!org && e.org === org;
      e.fit = {
        incumbent: inc && !e.ownOrg ? inc : null,
        gain: inc && !e.ownOrg && e.waa !== null ? e.waa - inc.waa : null,
      };
      e.fit.improves = e.fit.gain !== null && e.fit.gain > 0;
    }
  }

  return { entries, live, cleared, counts, offsets, incumbents };
}

export const FORTY_MAN_LIMIT = 40;

/**
 * 40-man occupancy for one org (ported from ootp-dashboard
 * app/src/utils/waivers.js fortyManSpots). A claim costs a 40-man spot, so the
 * board shows this next to the wire. Returns null when no row in the league
 * carries the 40-man flag (`On40Man`): unknown, not "40 open".
 */
export function fortyManSpots(hitters = [], pitchers = [], org) {
  const rows = [...(hitters || []), ...(pitchers || [])];
  if (!rows.some((p) => isOn40Man(p) !== null)) return null;
  if (!org) return { used: 0, open: FORTY_MAN_LIMIT, limit: FORTY_MAN_LIMIT };
  const used = rows.filter((p) => getOrg(p) === org && isOn40Man(p) === true).length;
  return { used, open: Math.max(0, FORTY_MAN_LIMIT - used), limit: FORTY_MAN_LIMIT };
}
