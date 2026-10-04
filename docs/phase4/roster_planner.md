# Phase 4 wave 2 — the Roster Planner on his app

Branch `phase4/planner`. This ports ours' Roster Planner (`app/src/views/RosterPlanner/*` and
`app/src/utils/rosterPlanning/*`) into `tgs-viz` as the page `/roster-planner`
("Roster Planner" under Organization in the sidebar). Words follow `bridge.md`: **ours** is
ootp-dashboard, **his** is this fork's `tgs-viz`. 🟢 computed from his data · 🟡 borrowed
constant · 🔵 deliberate assumption.

## 1. What the page does

You pick an org (default: the league's `my_org`, else the first org matching /cub/, else the
first org, the same rule as Org Builder and Waivers) and a plan year (the game year plus the
next three). The page shows:

- stat tiles: 40-man and active counts, open 40-man spots, Rule 5 players to protect, and
  40-man players whose status for the year is unknown;
- warnings: over the 40 / 26 limits, Rule 5 crunch, thin positional cover, rotation size;
- decision queues: arbitration (tender / non-tender), team options (accept / decline),
  contracts ending before the plan year (re-sign);
- drag-and-drop buckets: active roster (catchers, infield, outfield, DH, rotation, bullpen,
  with coverage tiles), short IL, 60-day IL, inactive 40-man, the Rule 5 shortlist with its
  FV slider, the minor-league pipeline, and Departing;
- smart suggestions (Rule 5 protects, DFA candidates, promotions) and a moves log you can
  reorder and undo.

Moves are saved in the browser under `ssb_roster_plan:<league>:<org>`. Every storage read and
write is guarded, so a private window still works; it just forgets the plan.

## 2. Files

| File | What it is |
|---|---|
| `src/lib/rosterPlanning/rosterRules.js` | Every constant the planner uses that is not read from the data: roster sizes (🔵 MLB defaults) and ours' advice thresholds (🟡). One module, so the list is auditable. |
| `src/lib/rosterPlanning/status.js` | Game year, contract year, and a player's status for one calendar year. |
| `src/lib/rosterPlanning/eligibility.js` | Roster state, Rule 5 and options from data flags; ours' `filterR5Protect` tiers. |
| `src/lib/rosterPlanning/projection.js` | The plan for one year: moves applied, buckets, 40-man / active counts, a per-year status map. |
| `src/lib/rosterPlanning/depth.js`, `crunch.js` | Ours' depth chart, coverage and crunch / suggestion logic on planner rows. |
| `src/lib/rosterPlanning/enrich.js` | `_war`, `_warP`, `_fv` (and role-locked `_sp` / `_rp`) from accessors. |
| `src/components/RosterPlannerParts.jsx` | Rows, droppable panels, coverage tiles, queues, suggestions, moves log. |
| `src/pages/RosterPlannerPage.jsx` | The page. |
| `tests/client/rosterPlanning.test.mjs` | 14 tests: 13 on synthetic records, 1 smoke run over every Cubs plan year on `public/data/SSB`. |

New dependencies: `@dnd-kit/core` 6.3.1, `@dnd-kit/sortable` 10.0.0, `@dnd-kit/utilities`
3.2.2 (the versions ours pins). `package-lock.json` gains only those packages, their
`@dnd-kit/accessibility` dependency and `tslib`.

## 3. Where each fact comes from

| Planner fact | His field (accessor) | Notes |
|---|---|---|
| Game year | `metadata.json` `game_date`; else the most common `SalaryStartYr` | 🟢 |
| Contract year (offseason roll) | most common `SalaryStartYr`, accepted only as game year or game year + 1 | 🟢 ours' rule, on his field |
| On 40-man / active | `isOn40Man` / `isActiveRoster`: export `On40Man` / `ActiveRoster`, else StatsPlus `IsOnSecondary` / `IsActive` | see §6, decision 1 |
| IL | `OnDL`, `OnDL60`, only for a 40-man player | 🔵 OnDL on a minor leaguer is his minor-league IL and does not move him |
| Status per year | `SalaryReport` / `SalaryReportSpan` (OOTP's team salary page), then `SalarySchedule` / `ContractOptions` | a year inside the report span with no cell is FA, as the page shows it |
| Rule 5 | `Rule5Eligible`, `YearsProtectedFromRule5` | eligibility now only; when a player becomes eligible is not in the data |
| Options | `OptionsUsed`, `OptionYearUsed` | remaining is unknown |
| WAR / potential / FV | `Max WAR wtd`, `MAX WAR P`; pitchers via `pickPitcherRole`; FV = ours' v21 `calcFutureValue` with `DEV_CURVE_DEFAULTS` | 🟡 curve defaults |

## 4. Ours' rules that were dropped

None of these has a data field, and the standing rule is to read OOTP's facts, not re-derive
its rules. Each is shown as unknown or left out:

- Super Two, the service-time accrual rule and the Super Two modal (ours `service.js`).
- Arbitration at 3 years, free agency at 6, the pre-arb / Arb-1..3 ladder
  (ours `eligibility.js parseContractStatus`). The salary report's own `arb` / `arb_uncertain`
  cells replace them.
- The Rule 5 signing-age rule and the draft-date fetch (ours `calcR5Projection`,
  `fetchDraftDates`). The "R5 in N years" countdown is gone; the tag says "R5 eligible".
- MiLB free agency after 7 years (ours `calcMLFA`), with its warning, suggestions and panel.
  A minor leaguer's later years read "MiLB (term unknown)".
- The 3-option limit, option burn, "last option year", "out of options", the demote block
  and the out-of-options queue.
- `_projection.baseline` (ours' pipeline output) and the DEM demand column on expiring deals.

## 5. Constants that remain (`rosterRules.js`)

- 🔵 Roster settings: 40-man 40, active 26, inactive 14, and "the 60-day IL is off the 40-man".
  OOTP sets these per league; no field in the pull carries them.
- 🟡 Ours' advice thresholds: cover of 2 (ideal 3) per position, a 5-man rotation, 8 in the
  bullpen, 12-14 active pitchers, inactive depth tiles (C / SS / CF 1, SP 2, RP 2), the
  24-player 40-man balance note, the R5 FV threshold 1.0 with a 0.2 buffer, the
  "not displaceable" rule (active with WAR 2.5+, or 2+ years at $20M+), and promote above WAR 1.5.
  They are planning advice. The WAR-valued ones (2.5, 1.5, the R5 FV threshold) are on ours'
  WAR scale and were not re-checked against his.

## 6. Decisions for the user

1. **The stale roster export makes some orgs' counts impossible.** On the 2044-05-09 SSB pull
   the export flags are dated 2043-12-28, 133 game days old. Export-first (the accessor's
   current rule, bridge decision 2) gives Cleveland 37 active players on a 26-man roster and
   Colorado 48 on the 40-man. The live StatsPlus flags give both exactly 26 active and at most
   40 on the 40-man. For the Cubs the two give 32 / 25 (export) against 34 / 26 (StatsPlus).
   Across the 40 SSB orgs with a 40-man, export-first gives 40-man counts of 26-51 and active
   counts of 16-37. **Recommendation: flip `isOn40Man` / `isActiveRoster` to StatsPlus-first
   (one line each in `accessors.js`), or at least for the planner.** I did not flip it here,
   because it is a shared accessor and the bridge left the call to you. The page names the
   export date and its age in the header, and the over-limit warnings fire.
2. **The 60-day IL and the 40-man.** The planner keeps a 60-day IL player off the 40-man
   count (`IL60_OFF_FORTY_MAN`). That is the MLB rule, not read from the data.

## 7. Verified vs inferred

**Verified by running (this session):**
- `node tgs-viz/tests/client/rosterPlanning.test.mjs`: 14 passed. All other
  `tests/client/*.test.mjs` still pass.
- `vite build` passes.
- In the browser on SSB, Chicago Cubs: the page renders (40-man 32/40, active 25/26, 0
  unknown statuses in 2044); the 2045 view shows 7 Rule 5 protects and 6 arbitration cases;
  a non-tender and a drag to the short IL both apply; the plan survives a reload; a name
  click opens the player drawer; the console shows no errors.
- The org-wide counts in §6 (a Node run over every SSB org).

**Inferred:** that OnDL on a minor leaguer means a minor-league IL stint.

**Not checked:** BLM, TGS and the other leagues (SSB-only focus). A league whose rows carry
neither export nor StatsPlus roster flags shows a notice and puts everyone in the pipeline.
