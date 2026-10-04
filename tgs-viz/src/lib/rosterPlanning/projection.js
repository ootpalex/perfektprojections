// ============================================================================
// projection.js — the roster plan for one display year (ours buildRosterProjection).
//
// Input rows are flat player records that the page has already given `_uid`,
// `_type`, `_age`, `_war`, `_warP`, `_fv` (and pitchers `_sp` / `_rp`). This
// module adds the roster state (`_st`, from data, then user moves), `_r5`,
// `_options`, buckets, and a per-year status map.
//
// Dropped from ours (rules with no data field — see roster_planner.md):
//   - Super-Two projection (service.js), the arb/FA service thresholds and the
//     pre-arb / Arb-N ladder (eligibility.js parseContractStatus);
//   - the option-burn cascade, "last option year" and "no options left"
//     (projection.js:312-353): they need the 3-option limit;
//   - the `_projection.baseline` fast path (ours' pipeline output).
// ============================================================================
import { getId, getName, isPitcher } from "../accessors.js";
import { rosterState, r5Info, optionsInfo } from "./eligibility.js";
import { projectYearStatus } from "./status.js";
import { IL60_OFF_FORTY_MAN } from "./rosterRules.js";

export const BUCKETS = ["active", "fortyMan", "ilShort", "ilLong", "r5Risk", "prospects", "departing"];

/** Planner row for one player (no moves applied). */
export function toPlannerRow(p) {
  const st = rosterState(p);
  return {
    ...p,
    _uid: p._uid ?? getId(p),
    _type: p._type ?? (isPitcher(p) ? "pitcher" : "hitter"),
    _st: st,
    _r5: r5Info(p, st.on40),
    _options: optionsInfo(p),
  };
}

function categorize(ep, status) {
  if (status?.status === "fa") return "departing";
  const st = ep._st;
  if (st.ilLong) return "ilLong";
  if (st.ilShort) return "ilShort";
  if (st.on40 && st.act) return "active";
  if (st.on40) return "fortyMan";
  if (ep._r5.exposed) return "r5Risk";
  return "prospects";
}

// Apply one move whose start year has been reached (ours' move switch, on `_st`).
function applyMove(ep, move, startYear) {
  const st = { ...ep._st };
  switch (move.action) {
    case "protect":
      st.on40 = true;
      ep._r5 = { ...ep._r5, isProtected: true, exposed: false };
      break;
    case "dfa": case "trade": case "release":
      ep._removed = true;
      break;
    case "promote":
      Object.assign(st, { act: true, on40: true, ilShort: false, ilLong: false });
      break;
    case "demote":
      st.act = false;
      break;
    case "ilShort":
      Object.assign(st, { ilShort: true, ilLong: false });
      break;
    case "ilLong":
      Object.assign(st, { ilLong: true, ilShort: false, on40: true });
      break;
    case "sign":
      st.on40 = true;
      ep._signedFrom = startYear;
      break;
    case "sign_milb":
      ep._signedMilbFrom = startYear;
      break;
    case "decline_option":
      ep._declinedOptionYear = startYear;
      break;
    case "accept_option":
      ep._acceptedOptionYear = startYear;
      break;
    default:
      break;
  }
  ep._st = st;
  if (st.on40 && ep._r5.exposed) ep._r5 = { ...ep._r5, isProtected: true, exposed: false };
}

const sortByVal = (a, b) => (b._fv ?? b._war ?? -999) - (a._fv ?? a._war ?? -999);

/**
 * @param {Array} teamRows   page-enriched rows of one org
 * @param {Object} o
 *   gameYear, contractYear — status.js detectGameYear / detectContractYear
 *   moves      — { [uid]: { action, startYear } } and year-scoped arb keys
 *                "t:<uid>:<year>" → { action: "tender" | "nonTender", uid, startYear }
 *   displayYear — the year the buckets are built for
 *   lastYear   — the last year the status map covers
 */
export function buildRosterProjection(teamRows, { gameYear, contractYear, moves = {}, displayYear, lastYear }) {
  if (displayYear == null) displayYear = gameYear;
  if (lastYear == null) lastYear = displayYear;

  // Earliest non-tender per player (year-scoped keys).
  const nonTenderByUid = {};
  for (const [key, mv] of Object.entries(moves)) {
    if (!key.startsWith("t:") || mv?.action !== "nonTender") continue;
    if (mv.uid == null || mv.startYear == null) continue;
    if (nonTenderByUid[mv.uid] == null || mv.startYear < nonTenderByUid[mv.uid]) nonTenderByUid[mv.uid] = mv.startYear;
  }

  const rows = teamRows.map((p) => {
    const ep = toPlannerRow(p);
    const nt = nonTenderByUid[ep._uid];
    if (nt != null && nt <= displayYear) ep._removed = true;
    const move = moves[ep._uid];
    if (move) {
      const startYear = move.startYear ?? move.year ?? gameYear + 1;
      if (startYear <= displayYear) applyMove(ep, move, startYear);
    }
    return ep;
  });

  const kept = rows.filter((ep) => !ep._removed);

  const years = {};
  for (let y = gameYear; y <= lastYear; y++) {
    const yd = {};
    kept.forEach((ep) => { yd[ep._uid] = projectYearStatus(ep, y, { gameYear, contractYear }); });
    years[y] = yd;
  }

  const buckets = Object.fromEntries(BUCKETS.map((b) => [b, []]));
  const dy = years[displayYear] || {};
  kept.forEach((ep) => { buckets[categorize(ep, dy[ep._uid])].push(ep); });
  Object.values(buckets).forEach((arr) => arr.sort(sortByVal));

  const on40 = (ep) => ep._st.on40 === true;
  const fortyManCount = [
    ...buckets.active, ...buckets.fortyMan, ...buckets.ilShort,
    ...(IL60_OFF_FORTY_MAN ? [] : buckets.ilLong),
  ].filter(on40).length;
  const activeCount = buckets.active.filter((ep) => on40(ep) && ep._st.act).length;
  const unknownStatus = kept.filter((ep) => dy[ep._uid]?.status === "unknown").length;
  const on40Known = rows.some((ep) => ep._st.on40Known);

  return { buckets, years, enriched: kept, fortyManCount, activeCount, unknownStatus, on40Known, gameYear, contractYear, displayYear };
}

/** Where a row sits in the projection (drag source). */
export function bucketOf(projection, uid) {
  for (const [b, arr] of Object.entries(projection.buckets)) if (arr.some((p) => p._uid === uid)) return b;
  return null;
}

export const plannerName = (ep) => getName(ep) ?? ep?._uid ?? "?";
