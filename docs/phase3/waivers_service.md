# Phase 3: live waiver clock, service detail, roster flags and the game date (audit)

Branch `phase3/contracts`. Written before the code. Numbers were reproduced offline from the saved
replies; the end-to-end run (section 7) used his own `refresh.py --from-cache` with the network
patched to fail.

## Summary

- His `/players` mapping keeps only `OnDL`, `OnDL60`, `DLDays`, `DFA`, `OnWaivers` and MLB service.
  His claim board (`src/lib/waivers.js`) therefore lists every `OnWaivers` or `DFA` player as
  claimable: 199 players in the saved SSB data (2044-05-02). Only 1 of them has days left on a claim
  clock; 39 of the 40 on waivers show 0 days left (cleared). The new keys let the app tell them apart.
  Nothing in the app changes until Phase 4.
- The league's in-game date was nowhere in the app's data. It is now written to
  `public/data/<LG>/metadata.json` as `game_date`. SSB had no `metadata.json` at all; it gets a
  two-key file.
- `has_received_arbitration` is False on every saved row in both caches, including 233 players
  that the OOTP export lists as in arbitration. It is kept as a key but should not be used.

## 1. Source fields (StatsPlus `/players`)

Saved replies: his `tgs-viz/ingest/.cache/sp/ssb/players.json.gz` (77,487 rows, game date 2044-05-02,
13,991 of them rostered/rated players); ours `leagues/SSB/.statsplus_cache.json.gz` (12,988 players,
game date 2043-12-14). Every field below exists with the same name in both. Blank (`''`) means
"not on a roster"; the app must read blank as unknown, never 0.

| StatsPlus field | New record key | Type | Observed (his 13,991 rated players, 2044-05-02) |
|---|---|---|---|
| `days_on_waivers` | `WaiverDays` | int | 0 on 13,932; 28 on 46; 26 on 8; 56 on 2; 7, 20, 25 on 1 each |
| `days_on_waivers_left` | `WaiverDaysLeft` | int | 0 on 13,990; 1 on 1 (player 62286, 7 days on waivers) |
| `has_received_arbitration` | `HasReceivedArb` | bool | `0` on all 13,991 |
| `pro_service_years`, `_days`, `_days_this_year` | `ProSvcYrs`, `ProSvcDays`, `ProSvcDaysTY` | int | e.g. 9 / 1,622 / 28 |
| `secondary_service_years`, `_days`, `_days_this_year` | `SecSvcYrs`, `SecSvcDays`, `SecSvcDaysTY` | int | e.g. 4 / 830 / 28 |
| `years_protected_from_rule_5` | `YearsProtectedFromRule5` | int | 5 on 8,971; 4 on 4,082; 0 on 938 |
| `is_on_secondary` | `IsOnSecondary` | bool | 1 on 1,653; 0 on 12,338 |
| `is_active` | `IsActive` | bool | 1 on 1,483; 0 on 12,508 |

Units: day counts are league-calendar days; a service year is not assumed (section 5).

### Meaning of the last three (from the roster-fields stream, re-checked here)

- `years_protected_from_rule_5` is StatsPlus's own per-player value. Our `contract_projection.py` derives
  Rule 5 length from signing age (5 years at 18 or younger, 4 otherwise); that is an OOTP rule we hard-coded
  and is not used here. The field is 0 on amateurs and retired players (it is filled on all 77,487 rows),
  so 0 means "none" and not "unprotected".
- `is_on_secondary` is StatsPlus's name. Joined to the OOTP export `org.csv` by player id (7,301 players
  in both), it equals the export's `ON40` flag on 7,263 (99.5%): 958 yes/yes, 6,305 no/no, 24 `ON40` yes
  but False, 14 `ON40` no but True. Likely the 40-man flag. Inferred, not stated by StatsPlus. The key
  keeps StatsPlus's name for that reason.
- `is_active` equals `ACT` on 7,281 (99.7%): 727 yes/yes, 6,554 no/no, 14 and 6 off. Likely the active
  roster. Inferred.
  (Both joins reproduced here against the 2043-12-14 cache and `org.csv`.)

## 2. What his code does today (verified by reading)

- `statsplus.attach_contract_injury` (ingest) reads `is_on_dl`, `is_on_dl60`, `dl_days_this_year`,
  `designated_for_assignment` (`DFA`), `is_on_waivers` (`OnWaivers`), `mlb_service_years/days/days_this_year`.
- `src/lib/waivers.js` (lines 20-21): "the data carries no 40-man flag". `isClaimable` = `OnWaivers || DFA`.
  Cross-tab of the saved data (OnWaivers, DFA, days_on_waivers, days_left):

| OnWaivers | DFA | days on waivers | days left | Players |
|---|---|---|---|---|
| no | no | - | - | 13,773 + 19 with old non-zero days |
| no | yes | 0 | 0 | 159 |
| yes | yes | 28 | 0 | 37 |
| yes | no | 56 | 0 | 2 |
| yes | no | 7 | 1 | 1 (the one live clock) |

Today the claim board shows 199 players (159 DFA only + 37 + 2 + 1). Whether a DFA-only player can be
claimed is OOTP's rule and is not in the data; not decided here.

## 3. What ours does

`model/src/statsplus.py:fetch_players` keeps these fields under their StatsPlus names in `meta`;
`app/src/utils/waivers.js` reads `is_on_waivers`, `days_on_waivers_left` (0 = cleared, so not
claimable; null = treated as claimable). In ours the other fields (pro/secondary service,
arbitration, secondary, active) are stored but nothing in the app reads them. Dec-2043 cache: 4
players with 1 day left, 1 with 238 days on waivers and 0 left.

The saved SSB data agrees with ours' reading: 39 of 40 on-waiver players have 0 days left.

## 4. `has_received_arbitration` (checked, not relied on)

The coordinator's note said our 2043-12-14 cache had 233 true. Reproduced result: it has 0.

- Ours (2043-12-14): False for all 12,988 players.
- His (2044-05-02): `0` for all 13,991 rated players.
- 233 is the count of `1 (arbitr.)` in the `YL` (years left) column of `org.csv`: 233 players OOTP lists
  as in arbitration. All 233 have `has_received_arbitration = False` in the Dec-2043 cache.

So the field is not set for players who are in arbitration in December either; a reset across the year roll
cannot be the explanation, because it is also False before the roll for players OOTP calls arbitration
players. With two snapshots both all-False, the data cannot say what the field tracks (it may mean
"has been through an arbitration hearing", which no one has yet, or it may be unused in OOTP 27). It is
emitted as `HasReceivedArb` so nothing is lost, and documented as unusable until a snapshot shows a True.
Do not drive any Super Two or arbitration logic from it.

## 5. Service-year length and season day (ported arithmetic)

`contract_projection.py` hard-codes 172 days per service year; his `serviceTime.js` hard-codes 172 and
says it was measured. `roster_clock.service_year_days(rows)` measures it from the `/players` columns:
for each league level, the number L that satisfies `mlb_service_years == mlb_service_days // L` on every
row, and it returns the L exact for the most rows.

SSB, 2044-05-02: level 1 (857 rows with days above 0) and level 2 (277) are exact for 172 only (0
violations); level 8 (701) is exact for 145 only; level 6 (129) for 144 and 145; levels 0 and 3 are
not exact for any L (players from other leagues' clocks). Overall 172 matches 13,431 of 13,991 rows
(96.0%), so a plain "best L over all rows" is only 9 rows ahead of 171; the per-level method is what
separates them. Result: 172, measured, not assumed.

`detect_season_day` (modal `mlb_service_days % L`, computed on the rows whose level obeys the identity):
28 on 2044-05-02. Cross-check by a different column: the modal `mlb_service_days_this_year` is 28 on 751
players. Same answer. `detect_limbo` (season complete but years behind days) is False on that date.
Neither function is wired into the pull; they exist so the app and the Phase 4 views have one tested
implementation. Super Two, free agency at 6 years and arbitration at 3 years are OOTP rules and are left out
(see contracts.md, section 7).

## 6. Game date in `metadata.json`

How `metadata.json` is written today: BLM / TGS by `extract_data.py` (from the sheets: `extracted_at`,
`league`, `datasets`, `matchups`); offline leagues by `offline_league.build_metadata`. The live pull
(`refresh.py --statsplus`) never wrote it, so SSB has none. The app reads only `metadata.matchups`
(all four readers use `metadata?.matchups?.[...]`), so a file without `matchups` is safe.

Change: `roster_clock.write_game_date(out_dir, league, game_date)`, called at the end of
`refresh.py --statsplus --write` with `S.fetch_date(base)`. That value is held in memory from the
`/contract` and `/players` reads of the same run (60 s), so it normally costs no request; if the hold
has expired it is one `/date` call, the same cheap gate every other read uses.

- Merges `"game_date": "YYYY-MM-DD"` into the existing object and keeps every other key and the file's
  indent. Creates `{"league": "SSB", "game_date": ...}` when there is no file.
- Writes through a temp file and `os.replace`. Never overwrites a file that is not a JSON object
  (returns "skipped: ..."). Returns "unchanged" when the date already matches.
- The date is the in-game date of the `/contract` + `/players` replies. In `--from-cache` mode the
  ratings can be older than that date; the date still describes the contract/waiver data.
- `extract_data.py` rewrites BLM / TGS `metadata.json` whole and drops `game_date` until the next pull.
- Interaction to know about: `pull_report.py` prints `metadata.json`'s modification time as a board
  date. Every pull now touches that file, so the report's metadata age is the pull time, not the last
  time the metadata constants changed. Left as is (decision below).
- The app's sidebar Game Date reads `rating_trends.json` (the `pulls[].g` of the latest pull, SSB:
  `2044-05-02`, equal to the new value). It can switch to `metadata.game_date` later.

## 7. Effect on the saved SSB data (end-to-end, `refresh.py --from-cache --write --calib BLM`)

Run offline with the saved replies and the network patched to raise. Compared with the committed
`public/data/SSB/*.json` (then restored):

- 13,991 players (6,866 hitters, 7,125 pitchers): 0 existing values changed, 0 keys lost.
- Every player gains: `WaiverDays`, `WaiverDaysLeft`, `ProSvcYrs`, `ProSvcDays`, `ProSvcDaysTY`,
  `SecSvcYrs`, `SecSvcDays`, `SecSvcDaysTY`, `YearsProtectedFromRule5`, `HasReceivedArb`, `IsOnSecondary`,
  `IsActive` (all 13,991).
- Contract keys (contracts.md): `SalaryStartYr` on 2,094; `ContractOptions` on 108; `ContractBuyouts` on 79;
  `ContractExt` on 140 (synthetic: built from the dashboard's Dec-2043 extension rows, because no real
  `/contractextension` reply is saved).
- File size: hitters.json 46.71 -> 48.42 MB (+3.7%); pitchers.json 38.13 -> 39.89 MB (+4.6%); the
  `_park` copies grow the same.
- `metadata.json` created: `{"league": "SSB", "game_date": "2044-05-02"}`.

Examples (SSB, 2044-05-02):
- Live claim: player 62286 (Jared Cornett, Dodgers): `OnWaivers` true, `WaiverDays` 7, `WaiverDaysLeft` 1,
  `ProSvcYrs` 9, `ProSvcDays` 1,622, `SecSvcYrs` 4, `HasReceivedArb` false.
- Cleared: player 57570 (Matt Freeman, Guardians): `OnWaivers` true, `DFA` true, `WaiverDays` 28,
  `WaiverDaysLeft` 0.

## 8. Choices

- 🟢 from data: all keys are StatsPlus values as given (blank stays absent); 172 and the season day are
  measured from the same rows.
- 🟡 borrowed: none.
- 🔵 assumptions: `IsOnSecondary` = 40-man and `IsActive` = active roster (inferred from a 99.5% /
  99.7% join to the OOTP export; documented, key names keep StatsPlus's words); a blank value means
  unknown. No threshold or rule is computed from these fields.

## 9. Verified vs inferred

Verified by running: field names and values in both saved caches; the cross-tabs; the 233 / 0 arbitration
finding; the ON40 / ACT joins; 172 and the season day; the end-to-end diff; 42 unit tests.
Inferred: what `has_received_arbitration` tracks; the 40-man and active meanings; that a DFA-only player is
or is not claimable.

## 10. Decisions for the user

1. `pull_report.py` metadata age: leave (recommended; one line in the report is slightly misleading),
   or change the board line to read `game_date`.
2. Whether DFA-only players belong on the claim board: needs an OOTP rule check, not a code change here.
3. Whether to stop emitting `HasReceivedArb` until a snapshot shows a True (cost: 13,991 small keys).
