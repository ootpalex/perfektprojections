// ============================================================================
// rosterRules.js — every constant the Roster Planner uses that is NOT read from
// the data. One module, so the list is auditable (docs/phase4/roster_planner.md).
//
// Two kinds live here, and only these two:
//   1. LEAGUE ROSTER SETTINGS — roster sizes and IL semantics. OOTP sets them in
//      the league setup; no field in the pull carries them (checked: metadata.json,
//      the player rows, the roster export). 🔵 MLB defaults, a decision for the user.
//   2. PLANNING HEURISTICS — ours' (ootp-dashboard) advice thresholds: how much
//      positional cover is "enough", when to suggest a promotion. They are not
//      OOTP rules and the planner never presents them as such. 🟡 borrowed from
//      ours' rosterPlanning/depth.js, crunch.js and eligibility.js.
//
// What is deliberately NOT here (the standing rule: never re-derive OOTP's
// rules): Super Two, the 3/6-year arbitration and free-agency thresholds, the
// Rule 5 signing-age rule, minor-league free agency after 7 years, the 3-option
// limit, option burn, the 172-day service year. The planner reads those facts
// from data fields or shows them as unknown.
// ============================================================================

// ── 1. League roster settings (🔵 MLB defaults; not in the data) ────────────
export const FORTY_MAN_LIMIT = 40;
export const ACTIVE_ROSTER_LIMIT = 26;
// The inactive part of the 40-man: what is left after the active roster.
export const INACTIVE_FORTY_SLOTS = FORTY_MAN_LIMIT - ACTIVE_ROSTER_LIMIT;
// A player on the long (60-day) IL does not count against the 40-man; the short
// (10/15-day) IL does. SSB's live StatsPlus flags agree for 29 of the 32 players
// on the 60-day IL (IsOnSecondary false); the planner needs the rule only for a
// move the user makes ("place on 60-day IL").
export const IL60_OFF_FORTY_MAN = true;

// ── 2. Planning heuristics (🟡 ours' advice, not OOTP rules) ───────────────
// The three WAR / FV cutoffs below were set on ours' WAR scale. They are moved to
// his by matching percentiles on SSB's 2044-05-09 pull (same players, joined by
// ID), so each picks the same share of players as in ours: ours 1.5 / 2.5 / 1.0.
// User decision 2026-10-04 (docs/PHASE4_STATUS.md).
// Active-roster cover (ours depth.js analyzeActiveCoverage).
export const COVERAGE_POSITIONS = ["C", "1B", "2B", "SS", "3B", "LF", "CF", "RF"];
export const ACTIVE_COVER_NEED = 2;          // eligible players per position, minimum
export const ACTIVE_COVER_IDEAL = 3;         // and ideal (C has no ideal)
export const ROTATION_SLOTS = 5;
export const BULLPEN_TARGET = 8;
export const ACTIVE_PITCHERS_MAX = 14;       // above: "over-pitched"
export const ACTIVE_PITCHERS_MIN = 12;       // below (on a near-full roster): "under-pitched"
export const NEAR_FULL_ACTIVE = 25;
// Inactive 40-man depth tiles (ours depth.js analyzeInactiveCoverage).
export const INACTIVE_TILE_NEEDS = { C: 1, SS: 1, CF: 1, SP: 2, RP: 2 };
export const INACTIVE_SP_SLOTS = 2;
// 40-man balance note (ours depth.js buildDepthChart).
export const FORTY_BALANCE_MAX = 24;
// Rule 5 protect shortlist (ours eligibility.js): FV threshold slider default and
// the "clearly better" margin over the weakest displaceable 40-man player.
export const R5_DEFAULT_THRESHOLD = 1.35;   // ours 1.0 (exposed R5 players, 92nd pct)
export const R5_PROTECT_BUFFER = 0.2;
// A 40-man player is not "displaceable" when he is a regular (active, WAR at or
// above this) or on a big guaranteed deal (years left and salary at or above these).
export const DISPLACE_KEEP_WAR = 2.8;       // ours 2.5 (active roster, 70th pct)
export const DISPLACE_KEEP_YEARS = 2;
export const DISPLACE_KEEP_SALARY = 20_000_000;
// Suggestions (ours crunch.js): promote an inactive 40-man player above this WAR;
// list sizes.
export const PROMOTE_WAR = 1.75;            // ours 1.5 (inactive 40-man, 81st pct)
export const DFA_SUGGESTIONS = 5;
export const PROMOTE_SUGGESTIONS = 3;
