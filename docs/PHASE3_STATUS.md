# Phase 3 status: data and ingest

*2026-10-03, branch `phase3-data` (built on `phase2-model`). Plan: ootp-dashboard
`docs/migration-plan:docs/MIGRATION_PLAN.md` §4. Audits in `docs/phase3/`. Everything was built
offline against saved StatsPlus replies; one live validation pull is still to do (below).*

## What was built

| Item | State | Audit |
|---|---|---|
| Draft pool from StatsPlus | `statsplus.fetch_draftpool` (his `_fetch_csv` rules); `draft.py --pool-source auto` (default): StatsPlus `/draftpool/` first, the OOTP export as fallback and for the columns StatsPlus does not send. SSB gets 8 draft files; the ratings already come from the pull (all 875 class players are in it). `--pool-source export` restores his old behaviour. **`/draftpool/` reply shape unverified.** | `draft_pool.md` |
| Contracts / options | New keys `SalaryStartYr`, `ContractOptions`, `ContractBuyouts`, `ContractExt` (from a new `/contractextension` read in the same pull). His Owed/control logic unchanged; an option-aware view is built and uncalled (decision below). | `contracts.md` |
| Waiver clock, service, roster flags | New keys `WaiverDays`, `WaiverDaysLeft`, `ProSvc*`, `SecSvc*`, `HasReceivedArb`, `YearsProtectedFromRule5`, `IsOnSecondary`, `IsActive`; `metadata.json` gains `game_date`. | `waivers_service.md` |
| Roster-management fields | Optional `roster_export` setting per league: an OOTP `org.csv` merged by player ID as new keys (`On40Man`, `OptionsUsed`, `Rule5Eligible`, `ContractStatus`, `FAType`, …) with the export's date and gap. Nothing happens without the setting. | `roster_fields.md` |
| His guards and pull report | Adopted as-is (wrong-league guard, typed refusals, token-age warning, honest pull report). | `adopted.md` |

**Standing rule applied:** no OOTP rule is re-derived. The plan's "derive Rule 5 from service +
signing age" was dropped; StatsPlus's own `years_protected_from_rule_5` is carried instead. Ours'
hard-coded Super Two, FA-at-6, arbitration-at-3, minor-league FA at 7 and 3 option years were not
ported (his `serviceTime.js` hard-codes FA 6 / arbitration 3; untouched).

**Offline integration check** (network blocked, date pinned to SSB's last pull): SSB rebuilt,
0 existing values changed, 0 keys lost; 15 new keys on all 13,991 players; option years on 108;
`metadata.json` `game_date` 2044-05-02. Tests: 377 Python, 355 Node, all passing.

**Correction (2026-10-03):** `refresh.py --from-cache` is not fully offline — it reads `/date`
every run and `/teams`, `/contract`, `/players` when the saved copies are over 6 hours old. The
Phase 1–2 SSB rebuilds therefore made about 7–8 small StatsPlus reads (no ratings job).

## Findings worth knowing

- **`has_received_arbitration` is unusable:** false for every player in both saved `/players`
  replies, including the 233 OOTP lists as in arbitration. Emitted, not relied on.
- **Several "export-only" fields are in `/players`:** `is_on_secondary` matches the export's 40-man
  flag on 99.5% of 7,301 players, `is_active` the active roster on 99.7%; `PROY`, `SECY/SECD`,
  draft fields and contract years-left match StatsPlus exactly.
- **Option-aware money (SSB, 2,094 priced players):** treating options as not guaranteed cuts
  Owed from $11,544M to $9,675M (−16.2%) and control years for 93 players.
- **SSB draft boards vs our dashboard's:** same players; rank correlation 0.89–0.93; top-25 overlap
  18–20 (a sanity check — ratings date, WAA scale and calibration all differ).
- **Our dashboard bug (not ours to fix here):** `model/main.py:355-359` can save an empty StatsPlus
  cache for a game date because `_fetch_csv` swallows errors.

## Decisions taken (2026-10-04)

- **Option-aware Owed/control: A** — the option keys ship as data; the app shows them in Phase 4;
  "C" (both readings) after a few odd contracts (buyout without an option flag) are checked in OOTP.
- **`org.csv`:** exported by hand from OOTP. SSB's `roster_export` (local settings) points at the
  file the dashboard already uses (`ootp-dashboard/leagues/SSB/csv/players/org.csv`), so one export
  feeds both; the merged keys carry the export's date and its gap to the pull.
- **Salary-report pages: keep** — they are the only source of OOTP's arbitration projections.
  Being ported onto his client (sequential, cached per in-game day).
- **Data-date report** shows each league's in-game date (from `metadata.json`) and no longer the
  `metadata.json` file time. **Draft task description** no longer says the pool needs an export
  (the echo texts of his TGS/BLM bat tasks stay — his Windows bat-equivalence test pins them).
- **Live validation pull:** approved, after the user's other agent finishes.

## Live validation pull (2026-10-04, approved)

`update.SSB` from the console: pull 576, in-game **2044-05-09**, 14,003 ratings rows. Every new read
worked on the first try:
- **`/draftpool/`**: columns `ID`, `Player Name` (as assumed), 828 players; 12 live picks; SSB draft
  boards 345 hitters / 483 pitchers. SSB's manifest entry rebuilt so the app shows them
  (`features.draft` true). *Gap for later:* the update task does not refresh a league's manifest when
  a new dataset first appears.
- **`/contractextension`**: same columns as `/contract`, one row per player; 32 signed extensions.
- **Salary-report pages**: 28/28 read through his client (28 fetched, 0 reused), 1,134 players;
  `ArbProjection` on 849 (487 uncertain). The live pages showed cells with several marks — `(P,O)`
  (a player option that is also an opt-out) and `(*auto)` (minor-league, marked auto) — which the
  ported parser left `unparsed` (23 cells); the parser now reads comma-separated marks into
  `marks` and every one of the 6,341 cells on the 28 pages parses. A trimmed real page is a test
  fixture.
- **`org.csv` merge**: 7,308 players matched; warned the export is 133 game days older than the pull.
- **Found and fixed:** the rating-trends lens and the ML rows priced SSB's vintages with SSB's own
  calibration ("The Sheets SSB" missing → WAA lens dropped; empty fingerprint → no WAA cache). Both
  now use the league's basis (BLM); the WAA lens ships for SSB.
- **Data-date report:** "SSB: OK - updated this run, in-game date 2044-05-09". Only the ML-score step
  failed (no trained models on this machine), as expected.

## Needs the user

1. **One live validation pull** (SSB): `/draftpool/` (shape, token, row count vs the 2044/2045
   classes) and `/contractextension` (header), via `update.SSB` plus one `fetch_draftpool` read.
2. **Option-aware Owed/control:** A show the new keys only · B switch to the guaranteed floor ·
   C show both. Recommendation: A now, C after a few contracts are checked in OOTP.
3. **`org.csv` export:** where it comes from on your side, and whether to configure `roster_export`
   for SSB.
4. Smaller: salary-report annotations (one page per team, ~30 requests — leave out?);
   `pull_report.py` could show `game_date` instead of the file time; the draft task wording
   ("needs an OOTP export") is stale.
