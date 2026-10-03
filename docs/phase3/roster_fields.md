# Phase 3 - roster-management fields (ON40, OPT, OY, R5, YL, IC, PROY ...)

Branch `phase3/roster`. Audit first, as the brief requires; the code that follows is described at the end.

Legend. 🟢 computed from data we hold. 🟡 borrowed constant (provenance named). 🔵 deliberate assumption.
"Verified" means I ran it against the saved files this session. "Inferred" means I reasoned from context.

## 1. What the question is

Our dashboard reads roster-management state from the OOTP `org.csv` screen export (184 data columns plus
`ID`; `ootp-dashboard/model/src/export.py:734-790` copies them into each player's `meta`). His pull has no such
columns: `/ratings` is 130 columns of ratings only (verified: `.cache/statsplus_ssb.json`, 13,991 rows x 130
keys, none of them contract or roster fields), and `src/lib/serviceTime.js:26-27` says option years, the 40-man
clock and Rule 5 status are "NOT AVAILABLE". `src/lib/waivers.js:20` and `src/pages/WaiverClaimPage.jsx:50,112`
say the same about the 40-man flag.

Standing rule (brief rule 2): a field with no StatsPlus source and no OOTP export is absent, never computed from
a rule we wrote.

## 2. Sources I checked

| Source | File | Game date | Rows |
|---|---|---|---|
| His `/players` | `tgs-viz/ingest/.cache/sp/ssb/players.json.gz` (main checkout) | 2044-05-02 | 77,487 rows x 62 columns (13,991 with a roster block, 63,496 retired or amateur rows with it blank) |
| His `/contract` | `.../sp/ssb/contract.json.gz` | 2044-05-02 | 13,991 x 40 |
| His `/ratings` | `.../statsplus_ssb.json` | pulled 2026-10-02 | 13,991 x 130 |
| Ours `/players` | `leagues/SSB/.statsplus_cache.json.gz` key `players` | 2043-12-14 | 12,988 x 39 (ours drops `ID`, names, ages, `mlb_service_years/days` as duplicative of the export; `statsplus.py:157-166`) |
| Ours `/contract` | same file, key `contracts` | 2043-12-14 | 9,046 |
| Ours `org.csv` | `leagues/SSB/csv/players/org.csv` | file written 2026-08-31 22:52 local; in-game date see 4 | 7,309 players, 185 columns |

Timing matters for every comparison below. Our StatsPlus cache was fetched 2026-09-01 03:35 UTC (game date
2043-12-14) and the org export was written 17 minutes later, but the export's latest transaction is dated
2043-12-28, so the game had advanced about two weeks between the two files. Same-vintage comparisons against
our cache therefore carry a small known skew (about 0.5% of rows). Comparisons against his 2044-05-02 pull
cross the 2044-01-01 service-year roll and are only usable for key coverage, not values.

## 3. Inventory - every roster-management field ours uses

"Ours uses" = read by the app from `meta` (file:line from this session's grep). "Match" = rate of exact agreement
between the export column and the named StatsPlus field on the 7,301 players present in both (ours cache, same
vintage up to the skew above). Verified unless marked inferred.

| Export col | Meaning (as ours uses it) | StatsPlus source | Match / evidence | Example values (org.csv) | Used by (ours) |
|---|---|---|---|---|---|
| `PROY` | professional service years | `/players.pro_service_years` | 100.0% (7,301/7,301) | 1, 5, 8 | `FreeAgentFinder.jsx:136`, `eligibility.js:97,121` |
| `SECY`, `SECD` | secondary-roster service years / days | `/players.secondary_service_years`, `.secondary_service_days` | 100.0% both | 3 / 565 | `_shared.js:4-6` |
| `MLY`, `MLD` | MLB service years / total days (years = floor(days/172); verified 7,309/7,309 in the export) | `/players.mlb_service_years`, `.mlb_service_days` (present in his `/players`; ours drops them, `statsplus.py:157-166`) | not testable same-vintage (ours cache lacks them; his is 4.5 months later) | 3 / 565 | `service.js`, `eligibility.js:13-21` |
| `Draft`, `Round`, `Pick`, `OA Pick` | draft year, round, pick, overall | `/players.draft_year`, `.draft_round`, `.draft_pick`, `.draft_overall_pick` | year 100%, pick 100%, overall 100%; round 98.4% (the export prints "3S" for a supplemental, StatsPlus puts the round in `draft_round` and the supplemental in `draft_supplemental`) | 2042 / 1 / 28 | `eligibility.js:96` (`meta.draft`) |
| `WAIV` | on waivers | `/players.is_on_waivers` (his `OnWaivers`, already mapped, `statsplus.py:1450`) | 99.8% | `-` / Yes | `WaiverWireView.jsx` |
| `DFA` | designated for assignment | `/players.designated_for_assignment` (his `DFA`, mapped, `statsplus.py:1448`) | 99.9% (export shows 10 Yes where StatsPlus shows 0; consistent with the 14-day skew, inferred) | `-` / Yes | `WaiverWireView.jsx` |
| `CV`, `TY` | current contract value / contract term years | `/contract` `salary{current_year}`, `.years` | `TY` = `years` 100% (7,207 rows with a contract); `CV` = salary at current year 87.7% (938 rows with a value; the rest differ, not diagnosed) | $1 200 000 / 1 | `export.py` meta `cv`,`ty` |
| `ECV`, `ETY` | extension value / years | `/contractextension` (ours `statsplus.py:64-92`) | 1 non-empty row in SSB | $28 500 000 / 4 | `meta.ecv` |
| `YL` | "years left" plus a qualifier, e.g. `2 (arbitr.)`, `1 (auto.)` | number: `/contract.years - current_year` (100% of the 7,207 rows with a contract, verified). Qualifier `arbitr.`: `/players.has_received_arbitration` (233 of 233 agree). Qualifier `auto.`: **export only**. No `club opt.` / `player opt.` / `vesting` strings occur in SSB; those options come from `/contract.last_year_*_option` | as stated | `1 (auto.)` 6,895; `1 (arbitr.)` 233; plain `4` 32 | `eligibility.js:13-60`, `service.js:90`, `WaiverWireView.jsx:128` |
| `ON40` | on the 40-man roster | **probably** `/players.is_on_secondary` | 99.48% (38 of 7,301 differ, all consistent with the two-week skew; inferred, not proven) | `Yes` 982 / `-` 6,327 | `strength.js:36`, `eligibility.js:16,93,134,155`, `projection.js:52,164`, `depth.js:175`, `waivers.js:88`, 8 views |
| `ACT` | on the 26-man active roster | **probably** `/players.is_active` | 99.73% (20 differ) | `Yes` 741 / `No` 6,568 | `projection.js:337`, `depth.js:175` |
| `OPT` | option years used so far (0-3) | **export only** (no option-years field in `/players` or `/contract`; the `/contract` option flags are contract options, a different thing) | n/a | 0: 6,521, 1: 395, 2: 219, 3: 174 | `eligibility.js:131`, `projection.js:314`, `WaiverWireView.jsx:129` |
| `OY` | option year being used this season (0-3). OOTP does not document the column; the app treats `> 0` as "an option is burned this season" (`projection.js:309-327`) | **export only** | observed: `OY>0` never occurs with `OPT=0` (0 rows); `OY>OPT` occurs on 37 rows, so it is not a subset count (the semantics are unverified) | 0: 6,923, 1: 331, 2: 43, 3: 12 | `projection.js:309-327`, `PlayerCompareView.jsx:96` |
| `R5` | currently Rule 5 eligible | **export only** as a flag. Its inputs are in StatsPlus: `/players.years_protected_from_rule_5` (values 0 / 4 / 5) and `draft_year`. See 3a. | n/a | `Yes` 2,171 (all with `ON40` = `-`) / `No` 5,138 | `Rule5Board.jsx:47`, `eligibility.js:94` |
| `ROOK` | rookie status | **export only** | n/a | `Yes` 4,870 / `No` 2,439 | `export.py:786` |
| `IC` | international complex | **export only**. Perfectly collinear with level `INT` (1,079 of 1,079). His `Lev` has no INT value and StatsPlus `Level` does not separate them (the 1,079 INT players sit in `Level` 0, 1, 4 and 6) | n/a | `Yes` 1,079 | `service.js:151` |
| `FAT` | free-agent type (A / B) | **export only** | n/a | A 1, B 6, `-` 7,302 | `meta` extras |
| `Sign` | signing difficulty | **export only** | n/a | Hard 3,221; Extremely Hard 2,950; Normal 782; Easy 347 | `export.py:789` |
| `DEM`, `DEM_1` | contract demand (the two columns are identical on all 7,309 rows) | **export only** (ours `salary_report.py` is a different thing: the salary report, not the player's ask) | n/a | `$860k` 11 rows; 7,275 rows `-` | `export.py:787` |
| `TXN`, `TXNDT` | last transaction and its date | **export only** | n/a | `Draft Pick`, `Jun. 2nd   2042` | `meta` extras |

### 3a. R5: StatsPlus carries the protection length even though the flag is export-only

`/players.years_protected_from_rule_5` is 5 for 8,971 and 4 for 4,082 of his 13,991 rostered players
(0 for 64,434 mostly retired rows). On our same-vintage data, for the 3,564 drafted, non-40-man, non-INT players:
`R5 == Yes` exactly when `(2043 - draft_year) >= years_protected_from_rule_5 - 1`, with 2 exceptions in 3,564.
This is inferred from one snapshot taken in the offseason; the `- 1` is the season-boundary convention at
December 2043 and I have not tested it in-season.

Consequence for ours. `eligibility.js:91-117` (`calcR5Projection`) derives the protection length itself:
`signingAge <= 18 ? 5 : 4` and, for undrafted players, `ceil(5 - proy)`. That is a rule we wrote (🔵), and the
standing rule says to flag it. StatsPlus supplies the per-player number directly. Using it is arithmetic on a
StatsPlus field, not a new threshold, but the `- 1` season convention is a rule, so I have **not** shipped an R5
flag computed from it. It is listed under decisions in the report.

## 4. Choice of the export date

The export carries no date column (verified: the only date-like column is `TXNDT`). Two proxies exist:
- the file's modification time (real calendar, 2026-08-31 for the saved file), and
- the latest `TXNDT` in the file, the newest in-game transaction: 2043-12-28 for the saved file. This is a
  lower bound on the export's game date (🟢 data, but it understates when no transaction occurred recently).

Against his 2044-05-02 pull the saved export is 126 game days old and its numbers sit on the wrong side of the
2044-01-01 service-year roll (`service.js:30` in ours: "MLY only rolls Jan 1"), so `PROY`, `MLY`, `OPT`, `OY`
and `YL` would all be a season behind. This is why the date is stamped on the records.

## 5. Where ours derives an OOTP rule (flags for the standing rule)

Not changed by this branch (the app is Phase 4); listed so they are not forgotten.

| Where | Rule we wrote | Class |
|---|---|---|
| `eligibility.js:91-117` | R5 protection 5 years if signed at 18 or under, else 4; undrafted `ceil(5 - proy)` | 🔵; StatsPlus `years_protected_from_rule_5` replaces it |
| `eligibility.js:119-127` (`calcMLFA`) | minor-league free agency after 7 pro years | 🔵, no source found |
| `eligibility.js:129-140` (`getOptionsInfo`) | three option years maximum | 🔵, no source found |
| `eligibility.js:53-55`, `service.js:4-5,89,207` | Super Two as MLB service 2.130 to 3.000 (`TWO_YEAR_FLOOR` 344 days; 130 days) | 🔵, 172-day year is measured in his `serviceTime.js:48` |
| his `serviceTime.js:50-51` | free agency at 6 service years, arbitration at 3 | 🟡 "OOTP league rules"; no field |

## 6. The merge design

Decision 1 - which fields. Only fields with **no verified StatsPlus source** are taken from the export: `OPT`,
`OY`, `R5`, `ROOK`, `IC`, `YL` (as OOTP's own string), `FAT`, `Sign`, `DEM`, `TXN`, `TXNDT`. `ON40` and `ACT` are also
taken from the export because the StatsPlus equivalents are 99.5% and 99.7% matches, not proven identical, and
the 40-man flag is the most used one. Fields StatsPlus supplies exactly (`PROY`, `SECY/D`, `MLY/D`, draft,
waivers, contract) are NOT copied: the `/players` and `/contract` stream owns them.

Decision 2 - where the export is found. A new optional per-league setting `roster_export`, validated in
`tools/settings.py` like `engine_first_season`. Absent means the layer is off and nothing changes. Value: a path
to the export file; a bare file name resolves inside `<save>/import_export/` (the folder `ingest/r5.py` already
reads), an absolute path or `~`/`%VAR%` path is used as given. I chose a setting over a fixed file name
because I cannot verify what OOTP names this screen's export (OOTP is not installed on this Mac, and the saved
file was renamed `org.csv` by hand); `r5.py` can fix a name because it knows the exact one. A setting needs no
guess and is the same pattern as the other optional per-league keys.

Decision 3 - safety against the wrong file. Player IDs are per-league. The merge joins on ID and also checks
the name (case-folded) on every matched row; a row whose name differs is skipped and counted. If at least 200
rows join and under half agree on name, the whole export is refused (🟡 the same thresholds as the wrong-league
guard at `refresh.py:326-332`).

Decision 4 - no overwrites. Keys are NEW and are only set when the record lacks them. A record not in the
export gets nothing (the field is unknown, not "No").

Decision 5 - staleness. Every merged record carries `RosterExportDate` (ISO, the proxy in 4) and, when the pull's
game date is known, `RosterExportGapDays` (pull game date minus export date; positive = export older). The pull
log prints both dates and warns when the gap exceeds 14 game days (🟡 the 14-day re-export convention of
`r5.py:52-55`, which uses file age; this uses game days because game time, not wall time, is what moves
the data).

## 7. Verified vs inferred

Verified (ran this session): every row count, match rate and example in 3; the YL and `has_received_arbitration`
agreement; `IC` collinear with `INT`; `MLD // 172 == MLY` in the export; names agree 7,307 of 7,308 with the
shipped SSB records (the exception is capitalisation: "PHIL PHELPS" against "Phil Phelps"); the 3a table.

Inferred: that `is_on_secondary` and `is_active` are the same notions as `ON40` and `ACT` (99.5% and 99.7% agree
but the skew prevents a proof); the meaning of `OY`; the `- 1` season convention in 3a; that the 38 `ON40`
mismatches are all skew.

Needs a live request: none against StatsPlus. The comparisons above need one pair of files at the SAME game
date: a fresh `org.csv` from the machine that has OOTP, exported on the day of a normal pull (the pull already
saves `/players`). That resolves the `ON40` / `ACT` / R5 questions without a new request.

## 8. What was built, and the result on the saved SSB data

Files: `tgs-viz/ingest/roster_export.py` (module, stdlib only), a 14-line hook in `tgs-viz/ingest/refresh.py`
(after the contract/injury attach, before the mapping check; wrapped so it can never stop a pull; asks for the
pull's game date through the already-memoised `fetch_date`, so inside the 60-second memo it adds no request),
`roster_export_problem` + `roster_export_path` + a docstring paragraph in `tgs-viz/tools/settings.py`,
`tgs-viz/tools/tests/test_roster_export.py` (33 tests, fixture `fixtures/roster_export/org_trim.csv`, 11 real rows).

Merging our saved `org.csv` into his saved SSB output (`public/data/SSB/hitters.json` 6,866 + `pitchers.json`
7,125 records, game date 2044-05-02), run through `python tgs-viz/ingest/roster_export.py --league SSB --csv
<org.csv> --data-dir <SSB data> --pull-date 2044-05-02` (reads, writes nothing). Verified by running:

- 7,308 of 13,991 records gain keys (3,663 hitters, 3,645 pitchers). 0 name mismatches. 1 export row has no
  record (an MLB player absent from his pull). No existing key collides with a new one.
- Keys added on those 7,308: `On40Man`, `ActiveRoster`, `OptionsUsed`, `OptionYearUsed`, `Rule5Eligible`,
  `RookieStatus`, `IntlComplex`, `ContractStatus`, `SignDifficulty`, `LastTransaction`, `LastTransactionDate`,
  `RosterExportDate`, `RosterExportGapDays` on all 7,308; `FAType` on 7; `ContractDemand` on 34.
- Values: `On40Man` true on 981, `Rule5Eligible` true on 2,171, `OptionsUsed` above 0 on 788, `IntlComplex` true on 1,079.
- The other 6,683 records get nothing: amateurs (2,909 AMA), free agents (1,468), and players who joined an org after
  the export (including 106 of his 966 MLB-level rows, 84 AAA, 748 AA). Their fields are unknown, not "No".
- Staleness: the export is dated 2043-12-28 (newest transaction; the file was written 2026-08-31) against the
  2044-05-02 pull: 126 game days old, and 32 real days older than the 2026-10-02 pull. The log prints a WARNING
  (over 14 game days), and every merged record carries `RosterExportDate: "2043-12-28"` and
  `RosterExportGapDays: 126`. In this state `OptionsUsed`, `OptionYearUsed`, `ContractStatus` and the 40-man are
  from before the 2044 service-year roll and should not be shown as current. A fresh export removes this.
- Size: about 340 bytes per matched record, 2.5 MB across hitters and pitchers, about 5 MB with the My-Park copies.

Not exercised: the hook inside `refresh.py` (a real run needs `/date`, which needs the network). The module, the
settings and the merge are covered by the tests above; the hook is 14 lines that call them.
