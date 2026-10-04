// ============================================================================
// status.js — a player's contract status for one calendar year, from data only.
//
// Port of ours' rosterPlanning/projection.js projectYearStatus + fromSpContract
// and service.js detectContractYear. What changed: ours fell back to its own
// service-time rules (pre-arb until 3 years, Arb-1..3, FA at 6, Super Two, MiLB
// FA after 7 pro years) when no data covered a year. Here the order is:
//   1. a user move (declined / accepted option, re-sign),
//   2. once the contract frame has rolled (offseason): the contract (SalarySchedule
//      / ContractOptions / ContractExt) for the years it covers,
//   3. OOTP's own team salary report (SalaryReport / SalaryReportSpan): a year in
//      the page's span with no cell is FA, as the page shows it,
//   4. the contract,
//   5. nothing: a 40-man player's status is "unknown"; a minor leaguer stays in
//      the minors with his term unknown (his MiLB free agency year is in no field).
// ============================================================================
import { getSalaryReportCell, getSalaryReportSpan, getContractYear, getSalarySchedule } from "../accessors.js";

// ours app/src/utils/helpers.js fmtSalary (display only).
export function fmtSalary(v) {
  if (v == null || !(v > 0)) return null;
  if (v >= 1000000) return `$${(v / 1000000).toFixed(v % 1000000 === 0 ? 0 : 1)}M`;
  if (v >= 1000) return `$${Math.round(v / 1000)}K`;
  return `$${v}`;
}

const mode = (values) => {
  const counts = new Map();
  for (const v of values) if (v != null) counts.set(v, (counts.get(v) || 0) + 1);
  let best = null, n = 0;
  for (const [v, c] of counts) if (c > n || (c === n && v < best)) { best = v; n = c; }
  return best;
};

/**
 * The in-game year the plan starts from. metadata.json `game_date` (written by
 * the pull from StatsPlus /date); else the most common contract start year
 * (`SalaryStartYr`); else null. Returns { year, source }.
 */
export function detectGameYear(metadata, players = []) {
  const gd = metadata && typeof metadata.game_date === "string" ? metadata.game_date.trim() : "";
  const m = /^(\d{4})-\d{2}-\d{2}/.exec(gd);
  if (m) return { year: parseInt(m[1], 10), source: "game_date", date: gd.slice(0, 10) };
  const yr = mode(players.map((p) => getSalarySchedule(p)?.startYear ?? null));
  return yr != null ? { year: yr, source: "contracts", date: null } : { year: null, source: null, date: null };
}

/**
 * Which calendar year the league's contracts are in force for (ours
 * service.js detectContractYear, on his `SalaryStartYr`). OOTP rolls contracts
 * to next season in the offseason while the calendar still reads the old year.
 * Only gameYear and gameYear + 1 are accepted; anything else → gameYear.
 */
export function detectContractYear(players, gameYear) {
  if (gameYear == null) return null;
  const best = mode(players.map((p) => getSalarySchedule(p)?.startYear ?? null));
  return best === gameYear || best === gameYear + 1 ? best : gameYear;
}

const OPTION_LABEL = { club: "Club Opt", player: "Player Opt", vesting: "Vesting Opt" };
export const FA = Object.freeze({ status: "fa", label: "FA", statusLabel: "FA" });
export const UNKNOWN = Object.freeze({ status: "unknown", label: "?", statusLabel: "Unknown" });

// Per-year status from the contract (ours fromSpContract), or null.
export function fromContract(p, year) {
  const c = getContractYear(p, year);
  if (!c || !(c.salary > 0)) return null;
  const label = fmtSalary(c.salary) || "Signed";
  if (c.optionType) {
    return { status: "option", label, statusLabel: OPTION_LABEL[c.optionType], optionType: c.optionType,
      buyout: c.buyout, salary: c.salary, guaranteed: true, source: "contract" };
  }
  return { status: "signed", label, statusLabel: "Signed", salary: c.salary, guaranteed: true, source: "contract" };
}

// One salary-report cell → status (ours projectYearStatus switch, verbatim
// labels). `accepted` = the user accepted a team option for this year.
export function fromReportCell(cell, accepted = false) {
  const label = fmtSalary(cell.salary) || (cell.type ? String(cell.type).toUpperCase() : "Signed");
  const g = cell.guaranteed;
  const base = { salary: cell.salary, guaranteed: g, source: "report", ann: cell.ann ?? null };
  switch (cell.type) {
    case "fa":             return { ...FA, source: "report" };
    case "milb":           return { status: "minors", label: "MiLB", statusLabel: "MiLB", ...base };
    case "milc":           return { status: "minors", label: "MiLC", statusLabel: "MiLC", ...base };
    case "arb":            return { status: "arb", label, statusLabel: "Arb", ...base };
    case "arb_uncertain":  return { status: "arb", label, statusLabel: "Arb?", ...base };
    case "team_option":    return accepted
      ? { status: "signed", label, statusLabel: "Accepted", ...base, guaranteed: true }
      : { status: "option", label, statusLabel: "Team Opt", optionType: "club", ...base };
    case "player_option":  return { status: "option", label, statusLabel: "Player Opt", optionType: "player", ...base };
    case "vesting_option": return { status: "option", label, statusLabel: "Vest Opt", optionType: "vesting", ...base };
    case "opt_out":        return { status: "signed", label, statusLabel: "Opt-out", ...base };
    case "retained":       return { status: "signed", label, statusLabel: "Retained", ...base };
    case "signed":         return { status: "signed", label, statusLabel: "Signed", ...base };
    default:               return { ...UNKNOWN, source: "report", raw: cell.raw ?? null }; // "unparsed"
  }
}

const accept = (st, ep, year) =>
  st.status === "option" && ep._acceptedOptionYear === year ? { ...st, status: "signed", statusLabel: "Accepted" } : st;

/**
 * Status of a planner row for `targetYear`. `ep` is a planner row (projection.js):
 * the flat player record plus `_st` (roster state after moves) and the move marks
 * `_declinedOptionYear`, `_acceptedOptionYear`, `_signedFrom`, `_signedMilbFrom`.
 */
export function projectYearStatus(ep, targetYear, { gameYear, contractYear }) {
  if (ep._declinedOptionYear != null && targetYear >= ep._declinedOptionYear) return { ...FA, source: "move" };
  if (ep._signedFrom != null && targetYear >= ep._signedFrom) {
    return { status: "signed", label: "Re-signed", statusLabel: "Re-signed", source: "move" };
  }
  if (ep._signedMilbFrom != null && targetYear >= ep._signedMilbFrom) {
    return { status: "minors", label: "MiLB", statusLabel: "Re-signed (MiLB)", source: "move" };
  }

  const cell = getSalaryReportCell(ep, targetYear);
  // Offseason: the report is still anchored to the completed season while the
  // contract has rolled; the contract wins for the years the roll reached.
  // milb / milc encode roster LEVEL, which the contract cannot express.
  const rolled = contractYear != null && gameYear != null && contractYear > gameYear;
  if (rolled && targetYear >= contractYear && cell?.type !== "milb" && cell?.type !== "milc") {
    const c = fromContract(ep, targetYear);
    if (c) return accept(c, ep, targetYear);
  }

  const span = getSalaryReportSpan(ep);
  if (span && targetYear >= span[0] && targetYear <= span[1]) {
    if (!cell) return { ...FA, source: "report" };
    return fromReportCell(cell, ep._acceptedOptionYear === targetYear);
  }

  const c = fromContract(ep, targetYear);
  if (c) return accept(c, ep, targetYear);

  if (ep._st?.on40 !== true) {
    // Not on the 40-man = on a minor-league deal this season (that is what the
    // 40-man is). When it ends (MiLB free agency) is in no field.
    return targetYear === gameYear
      ? { status: "minors", label: "MiLB", statusLabel: "MiLB", source: "roster" }
      : { status: "minors", label: "MiLB", statusLabel: "MiLB (term unknown)", termUnknown: true, source: "none" };
  }
  return { ...UNKNOWN, source: "none" };
}
