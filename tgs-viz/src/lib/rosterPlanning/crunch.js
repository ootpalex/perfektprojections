// ============================================================================
// crunch.js — roster-crunch warnings and suggested moves (ours crunch.js).
// Dropped from ours: the out-of-options warning and ordering (needs the
// 3-option limit) and the MiLB free-agency warning / suggestions (needs the
// 7-year rule). Neither has a data field. Thresholds: rosterRules.js.
// ============================================================================
import { FORTY_MAN_LIMIT, ACTIVE_ROSTER_LIMIT, PROMOTE_WAR, DFA_SUGGESTIONS, PROMOTE_SUGGESTIONS } from "./rosterRules.js";
import { plannerName } from "./projection.js";

const fmt1 = (v) => (v != null && Number.isFinite(v) ? v.toFixed(1) : "N/A");
const plural = (n, s = "s") => (n === 1 ? "" : s);

/**
 * Warnings for the display year. `r5Shortlist` is filterR5Protect's shortlist
 * (threshold-filtered) — the R5 lines count it, not every exposed prospect.
 */
export function analyzeCrunch(projection, { r5Shortlist = [], r5Threshold = null } = {}) {
  const warnings = [];
  const { fortyManCount, activeCount } = projection;
  if (fortyManCount > FORTY_MAN_LIMIT) {
    warnings.push({ type: "over40", severity: "error",
      message: `40-man roster has ${fortyManCount} players (${fortyManCount - FORTY_MAN_LIMIT} over the limit).` });
  }
  if (activeCount > ACTIVE_ROSTER_LIMIT) {
    warnings.push({ type: "over26", severity: "error",
      message: `Active roster has ${activeCount} players (${activeCount - ACTIVE_ROSTER_LIMIT} over the limit).` });
  }
  const n = r5Shortlist.length;
  if (n > 0) {
    warnings.push({ type: "r5", severity: "warning",
      message: `${n} Rule 5 eligible prospect${plural(n)} off the 40-man${r5Threshold != null ? ` at FV ${r5Threshold.toFixed(1)} or better` : ""}: drag into the 40-man to protect.` });
    const open = FORTY_MAN_LIMIT - fortyManCount;
    if (n > open && open >= 0) {
      warnings.push({ type: "crunch", severity: "error",
        message: `Protecting ${n} needs ${n} 40-man spots but only ${open} ${open === 1 ? "is" : "are"} open: clear ${n - open} spot${plural(n - open)}.` });
    }
  }
  if (projection.unknownStatus > 0) {
    warnings.push({ type: "unknown", severity: "info",
      message: `${projection.unknownStatus} 40-man player${plural(projection.unknownStatus)} ha${projection.unknownStatus === 1 ? "s" : "ve"} no salary-report or contract row for ${projection.displayYear}: status unknown.` });
  }
  return warnings;
}

/** DFA and promote suggestions (protect suggestions come from filterR5Protect). */
export function suggestActions(projection) {
  const { buckets } = projection;
  const score = (ep) => ep._fv ?? ep._war ?? 0;
  const suggestions = [];

  [...buckets.active, ...buckets.fortyMan]
    .sort((a, b) => score(a) - score(b))
    .slice(0, DFA_SUGGESTIONS)
    .forEach((ep) => suggestions.push({ type: "dfa", playerId: ep._uid, player: ep, action: "dfa",
      reason: `Lowest FV on the 40-man (${fmt1(ep._fv)})` }));

  buckets.fortyMan
    .filter((ep) => !ep._st.act && (ep._war ?? -999) > PROMOTE_WAR)
    .sort((a, b) => (b._war ?? 0) - (a._war ?? 0))
    .slice(0, PROMOTE_SUGGESTIONS)
    .forEach((ep) => suggestions.push({ type: "promote", playerId: ep._uid, player: ep, action: "promote",
      reason: `WAR ${fmt1(ep._war)}: ready for the active roster` }));

  return suggestions;
}

/** Reason line for an R5 protect suggestion (filterR5Protect tier entry). */
export function protectReason(entry, type) {
  const yp = entry.player._r5?.yearsProtected;
  const r5Tag = `R5 eligible${yp ? ` (${yp}-yr protection on file)` : ""}`;
  const fvTag = `FV ${fmt1(entry.score)}`;
  if (entry.reason === "openSlot") return `${r5Tag}, ${fvTag}: fills an open 40-man spot`;
  const d = entry.displacedPlayer ? plannerName(entry.displacedPlayer) : "weakest 40-man player";
  return `${r5Tag}, ${fvTag}: ${type === "protect" ? "displaces" : "edges"} ${d} (FV ${fmt1(entry.displacedScore)})`;
}
