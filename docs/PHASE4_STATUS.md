# Phase 4 status: app port and Night Scorecard restyle

*2026-10-04, branch `phase4-app` (built on `phase3-data`). Plan: ootp-dashboard
`docs/migration-plan:docs/MIGRATION_PLAN.md` §5. Detail docs in `docs/phase4/`. Built and checked on
SSB only (SSB-only focus, 2026-10-04); BLM, TGS and RG pages were not re-checked.*

## What was built

| Item | State | Doc |
|---|---|---|
| Bridge | `src/lib/accessors.js` (one read shape for ours' views over his flat columns), `fvV21.js`, `theme.js`; 134 accessor exports under test | `phase4/bridge.md` |
| Club lists | SSB's 28 MLB clubs from `metadata.json` `clubs` (`ingest/club_list.py`, `resolveLeagueClubs`); standings and strength boards no longer rank 22 foreign clubs | `phase4/bridge.md` |
| Restyle | Every one of his pages in Night Scorecard tokens: tables, player drawer, Control page, load and error screens, standings, Org Builder, Parks, Calibration, Dev Analysis, Make-it Odds, Market Value, Mock Draft, Roster Optimizer, Series Planner, Trends. Thresholds and calculations unchanged. | `phase4/restyle_pattern.md` |
| Roster Planner | Ported: drag-and-drop buckets, arbitration / option / expiring queues, Rule 5 shortlist, suggestions, moves log saved per league and org | `phase4/roster_planner.md` |
| Waiver Wire | Merged into his Waiver Claim page: claim clock, claimable / cleared split, 40-man occupancy, smart-rank toggles | — |
| Draft Board | "Mine" / "Taken" marks saved per league, merged with StatsPlus `draft_picks.json` | — |
| Prospects, Scout, Player Compare | Ported on his engine's numbers (WAA, projected peak) | `phase4/views.md` |
| Contract card | Player drawer shows options, buyouts, extension and OOTP's arbitration projection (Phase 3 keys) | — |
| Load speed | SSB Hitters settles in 7.5–9.3 s, down from 18.3–21.4 s (dev server, loaded machine); outputs byte-identical before and after | — |

**Standing rule applied:** no OOTP rule is re-derived. The planner dropped Super Two, the
arbitration-3 / free-agency-6 ladder, the Rule 5 signing-age countdown, minor-league free agency at 7
and the 3-option limit; each shows as unknown or is left out.

**Checks run on the merged branch:** `vite build` passes; every `tests/client/*.test.mjs` passes. In
the browser on SSB (Atlanta): Roster Planner, Waivers, Prospects, Scout, Org Builder, Market Value,
Control and the player drawer with the contract card render with real numbers and no console errors.
Market Value's stat cards clip their values below about 900 px of width; they fit at 1440.

## Decisions taken (2026-10-04)

- **Roster flags: StatsPlus first, the OOTP export as fallback.** The export is made by hand and goes
  stale. Export-first gave impossible counts on the 2044-05-09 pull (Cleveland 37 active, Colorado
  48 on the 40-man). With StatsPlus first, all 28 SSB MLB clubs are at or under 40 and 27 have
  exactly 26 active. Atlanta shows 27 because of one A+ player (Jesus Salmeron) that StatsPlus flags
  active but not on the 40-man.
- **All other Phase 4 decisions: the recommendations.** Evidence: an SSB comparison of both apps on
  the same players (2044-05-09 pull, joined by ID; his values run about 0.3 WAR higher on the
  40-man and spread about 0.9x as wide).
  1. *Pitcher best position* (SP-vs-RP thresholds −0.5 / 1.0): **kept.** The 1.0 RP-advantage
     cutoff never decides a label in either app; every "RP\*" comes from the −0.5 floor. His data
     gives 39 RP\* of 882 starters for any floor from −0.5 to +1.0; the two apps agree on 96.7% of
     781 matched starters.
  2. *Roster Planner cutoffs:* **moved to his scale by percentile** — promote 1.5 → 1.75, regular
     (not displaceable) 2.5 → 2.8, Rule 5 shortlist default 1.0 → 1.35. Unchanged, they flagged
     30–70% more players than ours (promote 77 vs 59, regulars 292 vs 217, Rule 5 275 vs 165);
     moved, they reproduce ours' counts (59, 218, 159).
  3. *Waiver smart-rank constants:* **kept.** His hitter spread is 0.86–0.89x ours, a ~12% change
     smaller than the constants' own uncertainty; toggles are off by default. The reliever 0.375x
     is an innings ratio, independent of the WAR scale.
  4. *Scout fit bonuses:* **kept** (same constants as 3; the positional-need bonus is per SD).
  5. *Prospect tier $ values:* **kept**; revisit with the market-value work.
  6. *Prospect definition:* **ours' fewer than 45 MLB days.** StatsPlus has no rookie flag;
     "secondary service" is 40-man service time (186 of the 353 prospects with any are under 25),
     so it cannot screen out foreign veterans.
  7. *Roster sizes 40 / 26:* **kept**; the live flags fit them (27 of 28 clubs at exactly 26 active,
     none over 40).
  8. *60-day IL off the 40-man:* **kept** (StatsPlus agrees for 29 of 32 SSB players on it).
  9. *Price for uncontracted players:* **null.**
  10. *StrictMode:* **removed** from `main.jsx`. The launcher runs the dev server, where StrictMode
      ran every valuation step twice.

## Needs the user

Nothing open for Phase 4.

## Follow-ups (no decision needed)

- The Waivers and Roster Planner org dropdowns still list KBO and South African clubs; they should
  use `resolveLeagueClubs()` like the standings.
- Market Value stat cards clip below ~900 px width.
- `useLeagues` downloads DEV's 9.8 MB `rating_trends.json` on every start only to test that it exists.
- Re-export `org.csv` from OOTP when convenient: Rule 5 and options used still come only from it, and
  this one is 133 game days old.
- ML models from the original creator are still awaited (the prospect board's ML source is empty).
