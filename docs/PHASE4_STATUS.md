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

## Needs the user

Constants carried from ours that were set on ours' WAR scale and never checked on his:

1. **Pitcher best position:** SP-vs-RP WAR thresholds −0.5 / 1.0 (`bridge.md` decision 1).
2. **Roster Planner advice cutoffs:** protect at FV 1.0, not displaceable at WAR 2.5, promote at
   WAR 1.5.
3. **Waiver smart rank:** injury adjustments (Iron Man +0.5 … Wrecked −2.0 wins), intangibles at
   0.15 wins per 10 grade points, relievers scaled 0.375×.
4. **Scout fit bonuses:** positional need, injury proneness, intangibles, reliever scaling.
5. **Prospect tier dollar values.**

Other decisions:

6. **Prospect definition:** ours' "under 45 MLB days" admits veterans signed from abroad (a
   35-year-old major-league starter is on the board). StatsPlus has no rookie flag; OOTP's
   `RookieStatus` comes only from the export (7,308 of 14,003 SSB rows).
7. **60-day IL off the 40-man:** the MLB rule, held as a constant (`IL60_OFF_FORTY_MAN`).
8. **Price for uncontracted players:** null (recommended) vs a league minimum the data does not carry.
9. **Roster sizes 40 / 26:** constants; no data field carries them.
10. **StrictMode in development:** turning it off roughly halves the remaining dev-server main-thread
    work (4.5–6.8 s vs 9.4–10.1 s, noisy); no effect on a production build. Left on.

## Follow-ups (no decision needed)

- The Waivers and Roster Planner org dropdowns still list KBO and South African clubs; they should
  use `resolveLeagueClubs()` like the standings.
- Market Value stat cards clip below ~900 px width.
- `useLeagues` downloads DEV's 9.8 MB `rating_trends.json` on every start only to test that it exists.
- Re-export `org.csv` from OOTP when convenient: Rule 5 and options used still come only from it, and
  this one is 133 game days old.
- ML models from the original creator are still awaited (the prospect board's ML source is empty).
