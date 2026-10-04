# Phase 4 views — Prospects, Scout and Player Compare on his data

Branch `phase4/views`. Wave 2. Three of ours' views now run in the fork on his rows and his FV engine.

Words used throughout (as in `bridge.md`):
- **Ours** is ootp-dashboard, `app/` on `main`.
- **His** is this fork's `tgs-viz`.
- **FV engine** is his `usePlayersWithFV` hook (`hooks/usePlayerData.js`). It stamps each row with a projected peak (`_potentialWAA`, shown as "Proj Pot" on his boards), the current value (`_currentWAA`), the listed potential (`_rawPotentialWAA`) and the source of the peak (`_potentialSource`: ML model, DEV cell, measured DEV curve, or assumed model). All of these are WAA.

Legend: 🟢 computed from his data · 🟡 borrowed constant, provenance named · 🔵 deliberate assumption.

Scope: SSB only. Built and checked on SSB, per the standing SSB-only rule. Nothing was checked on BLM, TGS or RG.

## 1. What was added

| File | What it is |
|---|---|
| `src/pages/ProspectsPage.jsx` | Ours' `ProspectsView.jsx`: The Board (tier config, filters, ranked board) and Farm Rankings (table and stacked $ chart). Route `/prospects`. |
| `src/pages/ScoutPage.jsx` | Ours' `ScoutView.jsx`: positional strength of another club against yours, trade targets at your weak positions, and that club's roster. Route `/scout`. |
| `src/pages/PlayerComparePage.jsx` | Ours' `PlayerCompareView.jsx`: up to five players side by side. Route `/compare`. |
| `src/lib/prospectTiers.js` | Ours' `utils/prospects.js` plus the tier constants from `utils/constants.js`. The tier search, tier assignment, farm rankings and scouting report are ours, verbatim apart from the player reads. |
| `src/lib/scoutFit.js` | Ours' trade-fit score (`applySmartRank`, restricted to the Scout page's four toggles), `calcOrgNeed`, and the trade-opportunity rule, over his positional-strength cells. |
| `src/lib/viewFormat.js` | Ours' `helpers.js` formatters, search, `orgLabel`, and the intangibles composite and 20-80 grade from ours' Dashboard enrich step. |
| `src/components/oursUi.jsx` | The `shared.jsx` primitives these pages use (`Section`, `SortHeader`, `PillBtn`, `TabGroup`, `MultiSelectDropdown`, `PositionFilter`, `LevelFilter`, `Toggle`, `Pagination`, `SearchInput`) plus a `PageHead`. Styled from `theme.js` `S` / `TOKENS`, as ours is. |
| `tests/client/views.test.mjs` | 12 tests over the three libs, including one on SSB's saved rows. |
| `src/App.jsx` | A "Scouting" group in the sidebar with the three links, and the three routes. |

Every player read goes through `lib/accessors.js`. The pages read the FV engine's stamped fields (`_potentialWAA` and so on) by name, because those are computed fields, not data columns.

The pages keep ours' inline-style grammar (`S`, `TOKENS`) rather than the `ns-*` classes from `restyle_pattern.md`. Both draw on the same tokens, so they render alike.

## 2. What changed from ours, per view

### Prospects

- **The FV a prospect is tiered on is his projected peak, not ours' v21 FV.** Ours computed FV as current + gap × credit-age, with a hand-tuned curve. That curve is not ported. His FV engine supplies the value instead, and the new "Src" column says which path produced it. On SSB today: 6,206 of 6,447 prospects come from the DEV cell and 241 from the measured DEV curve. No row comes from the ML model, because SSB has no `dev_ml.json` on this pull (inferred from the source counts).
- **Units are WAA.** The value columns are FV (projected peak), WAA (current) and Pot WAA (listed potential). Ours showed FV, WAR and WAR P. The tier cuts are therefore WAA too. The tiers are cut by rank against FanGraphs tier populations, so the method does not depend on the unit.
- **Dev% is gone.** His data ships no DEV percentile curve (`bridge.md` §4).
- **The pool is the league's own clubs only.** SSB's rows also carry other leagues' clubs (KBO and NPB, for example "kt wiz"). Before this filter, 1,063 of 7,510 pool rows belonged to those clubs, and they took tier slots scaled to 28 teams. The club list is the one the standings use (`resolveLeagueClubs`).
- **"Prospect" is ours' rule, kept:** in a club, not AMA or FA, and under 45 days of MLB service 🟡. This is ours' definition, not OOTP's. It admits veterans signed from abroad with no MLB service. Kutre Masya (35, MLB starter) is an example on SSB.
- **The "MLB players ≥ FV" column counts the FV engine's current WAA** for big-league squad players: Lev MLB, and not known to be off the 40-man. Where the 40-man flag is unknown, the level decides.
- **Saved settings** live under a new key, `ns-prospect-board-v1::<league>`. Ours' saved cuts are in WAR and must not load here. With nothing saved, the board uses the suggested cuts and saves only after an edit.
- **Fixed:** ours' `suggestThresholds` read one row past the end of the pool when the pool is smaller than the FanGraphs cumulative population, and threw. It now reads the last row. A test covers a 300-player pool.

### Scout

- **Positional strength is his engine** (`lib/positionalStrength.js`). It scores starter WAA per lineup slot, the top 5 SP and the top 8 RP. Each position gets a z-score and a rank within the league. The two lenses are Majors and Farm. Ours' "Now" and "Farm" were ours' depth-weighted WAR engine, which is not ported.
- **The fit baseline is the listed potential WAA** (`_rawPotentialWAA`), the counterpart of ours' WAR P. The Future Value toggle switches it to the projected peak.
- **Ours' bonuses are unchanged** 🟡: org need 0.12 wins per SD of weakness, the proneness table, 0.15 wins per 10 points of intangibles grade, and the RP scale 0.375. They are additive win deltas, so they carry over in unit. Their size against his spread was not checked.
- **Trade targets** are the scouted club's players at your below-average positions whose fit is above replacement. Ours tested fit > 0 on WAR. Here the test is fit + the replacement offset of the role the potential is priced on > 0, using his engine's per-league offsets 🟢.
- **Your club** defaults to the league's `my_org` setting, else the first club. A "Your club" picker was added, because ours took it from league settings.
- **The 40M column is tri-state:** ✓ on the 40-man, blank off it, "—" when the row is not in the roster export.

### Player Compare

- **Value rows** show the projected peak and its source, WAA and WAA potential, and WAR and WAR potential beside them. WAR is present on SSB.
- **Pitchers** show SP and RP WAA, potentials, WAR, the Starter flag, stamina, and velocity. Velocity is OOTP's range string ("92-94"), because his data has no numeric velocity.
- **Intangibles:** the 20-80 composite plus Intelligence, Work Ethic, Leadership, Loyalty and Greed. Adaptability is dropped because it is not in his data. The composite renormalises its weights over the five traits present 🔵.
- **Greed's colour is inverted.** High greed is bad, but ours painted it green.
- **Service time is OOTP's own figures**, years and total days ("3 yr · 619 d"). Ours split the days on a 172-day season, which re-derives an OOTP rule.
- **Options:** the row shows options used (`OptionsUsed`).

### All three

- Ages are whole years, because his data has no DOB.
- The two-way badge is dropped, because `isTwoWay` is always null on his rows.
- `LevelFilter` has no per-rookie-team rows, because his rows carry no team abbreviation.
- Ours' `Pagination` toggled a border colour over a border shorthand, which makes React warn on every page change. The port always sets the colour.

## 3. Verified vs inferred

**Verified by running (this session, SSB):**
- `npm run build` passes.
- All 9 `tests/client/*.test.mjs` pass, including `views.test.mjs` (12 of 12).
- `control/test/{fileMap,guards,pythonMain}` pass.
- In a browser on `npx vite`, with SSB loaded:
  - **Prospects:** 6,447 prospects in 28 clubs, and 1,138 tiered on the board.
  - **Tier config:** the cuts descend from +4.08 (tier 80) to −0.84 (tier 35+), and 612 of 735 MLB squad players are at or above the lowest cut.
  - **Farm Rankings:** 28 clubs and the stacked chart render. Washington is first at $488.5M.
  - **Scout:** both strength tables, the trade-opportunity callout, trade targets (76 with no toggles, 68 with all four on), and the roster table render. The Farm lens switches.
  - **Player Compare:** a hitter and a pitcher side by side.
  - **PlayerDetail** opens from the board.
- No console errors after the pagination fix.

**Inferred, not checked:**
- That SSB lacks `dev_ml.json` on this pull. I read this from the source counts and did not look for the file.
- That ours' bonus constants are sized sensibly for his WAA spread.

**Not checked:** BLM, TGS and RG, which are out of scope under the SSB-only rule. Visual layout was checked through page text and DOM reads only: the browser pane was hidden, so no screenshot was taken.

## 4. Decisions for the user

1. **The prospect definition.** Ours' "under 45 MLB days" admits veterans signed from abroad. The alternative is OOTP's own rookie flag (`RookieStatus`), which SSB carries only on export rows (7,308 of 14,003). **Decided 2026-10-04: ours' rule.** StatsPlus has no rookie flag, and its secondary service is 40-man time, so it cannot screen out foreign veterans.
2. **The tier $ values** are ours' defaults, set on ours' WAR boards 🟡. Tiers are cut by rank, so a tier means the same population either way. The $ per tier was never derived from his data. **Decided 2026-10-04: leave them; revisit with the market-value work.**
3. **The scout bonus constants** (§2 Scout). **Decided 2026-10-04: kept.** His hitter spread is 0.86–0.89x ours; the positional-need bonus is per SD.
