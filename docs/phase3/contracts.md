# Phase 3: contracts, options and buyouts (audit)

Branch `phase3/contracts`. Written before the code; the numbers below were reproduced by
`python tgs-viz/ingest/contract_terms.py ssb` (offline, reads the saved replies).

## Summary

- The app's Owed (total money left) and control years (seasons the club still holds the player)
  count every option year as guaranteed. On the saved SSB data that overstates Owed by $1,869.7M
  (16.2% of the $11,544.3M league total, 2,094 priced players) if no option is exercised, and
  overstates control years for 93 of the 101 players who have an option year still to come.
- StatsPlus already supplies everything needed to see this: `/contract` carries option flags and
  buyout amounts for every contract. His ingest drops them. This change keeps them as new record keys
  (`ContractOptions`, `ContractBuyouts`, `SalaryStartYr`, `ContractExt`) and changes no existing key.
- His Owed / control logic is not touched. The option-aware pricing is a gated proposal at the end
  (`option_aware_view` in `contract_terms.py`; nothing calls it).
- One request shape is unverified: no `/contractextension` reply is saved anywhere. The parser relies
  on it having the `/contract` layout. The only evidence is indirect (section 3). One live read
  confirms it.

## 1. Source fields

Saved reply: `tgs-viz/ingest/.cache/sp/ssb/contract.json.gz` in the main checkout, 13,991 rows,
game date 2044-05-02, 41 columns. One row per player_id (0 duplicates).

| Field | Meaning (as observed) | Observed |
|---|---|---|
| `season_year` | calendar year of contract year 0 | 2044 on 1,855 major-league deals; 0 on 7,205 placeholder rows with no deal |
| `current_year` | index of the year in force | `season_year + current_year` = 2044 on 2,084 of the 2,094 priced rows |
| `years` | length of the deal | 0 (4,688 rows), 1 (9,033), 2..8 (the rest) |
| `salary0..salary14` | pay of contract year i, dollars | 0 beyond `years` |
| `last_year_{team,player,vesting}_option` | option on contract year `years-1` | 59 team, 38 player, 11 vesting |
| `next_last_year_{team,player,vesting}_option` | option on contract year `years-2` | 3 team, 7 player, 0 vesting |
| `last_year_option_buyout`, `next_last_year_option_buyout` | dollars in the slot | see section 2 |
| `is_major` | major-league deal | 2,034 of 2,094 priced rows are 1 |
| `minimum_pa`, `*_bonus`, `mvp_bonus`, ... | performance bonuses | not read here; they are not option terms |

108 contracts carry at least one option flag. All 108 are major-league deals and all 108 are among the
2,094 priced players (those whose current-year salary is above 0). 101 of them have the option year
after the year in force; 7 have it on the year in force (already decided: the player is playing it).

### Checks that the field reading is right

- Calendar year of contract year i is `season_year + i`. Check: the dashboard's salary report (the
  per-team HTML table, 2043-12) labels 81 option cells for players that have a contract row. 75 of
  the 81 sit exactly on a year where the flag fires (`years-1` or `years-2`). 6 do not (section 2).
  Verified by running.
- A 139-of-140 match: the dashboard's saved `/contractextension` rows (2043-12) equal the `/contract`
  row of the same player in the 2044-05-02 reply (same `season_year`, `years`, salary list). The
  extension is therefore a signed deal that becomes the base contract at the next roll. The one
  exception (player 61432, extension starts 2045) is still pending, as expected. Verified by running.
- Extension start: for all 140 saved extensions `ext.season_year == base.season_year + base.years`.
  Verified by running.

## 2. What is not understood (kept raw, not interpreted)

- **Buyouts without a flag.** In 49 contract slots the buyout field is above 0 while no option flag
  is set in that slot. Examples: `next_last_year_option_buyout` is above 0 on 29 of the 59 contracts
  whose only flag is `last_year_team_option`. These might be opt-out clauses (the salary report has
  a separate "(O)" opt-out type, 20 cells in the saved report) but no column says so. They are kept
  as `ContractBuyouts` and tied to nothing.
- **Missing flags.** 6 of the 81 salary-report option cells have no flag in the contract row (for
  example player 57774: report says player option for 2044, contract has buyouts of $3.0M / $1.8M and
  no flag). The flag may be cleared once the option year is the year in force. Not resolved.
- **Team-option buyouts are clean.** All 62 team options carry a buyout above 0 in their own slot.
  Player options carry one in 7 of 45 cases, vesting options in 0 of 11. The proposal therefore adds
  a buyout only for team options.
- **Vesting conditions.** The trigger for a vesting option is not in the reply. Treated as not
  guaranteed and not club-controlled in the proposal.

## 3. `/contractextension`

Ours: `model/src/statsplus.py` (`fetch_contracts`, lines ~64-130) fetches `/contract` and
`/contractextension`, parses both with one function and attaches the extension as a sub-dict.
His `statsplus.py` had no extension fetch. Added in this branch:
`fetch_contract_extensions(base, cache=, fresh=, token=)`, same `_fetch_csv` path as `/contract`:
the `/date` gate, 6-hour reuse keyed on the in-game date, typed refusals, token redaction, one
request at a time. An empty body or a header-only body is "no extensions". It is called once in
`refresh.py` right after `/contract` and `/players`, from the same pull. A refusal or network error
there prints a note and drops `ContractExt` for that run; it never stops the pull.

Unverified: the exact header of a real reply. Evidence for the `/contract` layout: the dashboard
parses it with the `/contract` parser and 140 rows came out with real player ids and salary lists that
reappear as base contracts. Needs one live read (see the report's last section).

Why it matters for money: in the 2043-12 snapshot 140 players had extensions worth $219.7M over 179
player-years that are not in `SalarySchedule` (their remaining base deals total $56.1M). By
2044-05-02 the roll has moved them into the base contract, so the gap is an offseason effect.

## 4. Where his Owed and control numbers come from today (verified by reading)

1. `statsplus.attach_contract_injury` builds `SalarySchedule = [salary{y} for y in range(current_year, years)]`
   (only if any entry is above 0) plus `Price`, `ContractYrs`, `ContractYr`. Option flags and buyouts are
   not read.
2. `src/hooks/usePlayerData.js` (~:743) `_owed = sum(SalarySchedule)`.
3. `src/lib/serviceTime.js` `controlWindow`: `contractYears = SalarySchedule.length`;
   `controlYears = max(ceil(6 - MLBSvcDays/172), contractYears)`.
4. `src/lib/marketValue.js` (~:39, ~:1309) values surplus over every remaining `SalarySchedule` year and
   uses `sum/years` as the contract AAV (average annual value).

Consequence: every option year is priced at full salary and counted as controlled, whoever holds the
option. STATUS.md (line 133) records the same defect for TGS (~149 contracts).

## 5. Quantification on the saved SSB contracts (game date 2044-05-02)

Population: the 2,094 priced players (the records that carry `SalarySchedule`). Readings:
`as_is` = today. `guaranteed` = only the years before the first option year, plus the buyout when that
first option is a team option (what the club owes by declining). `club_holds` = as guaranteed, but
consecutive team options are kept (the club can exercise them); stops at the first player or vesting
option.

| Reading | Player-years | Owed (dollars) | vs as_is |
|---|---|---|---|
| as_is | 2,594 | 11,544.3M | |
| guaranteed | 2,483 | 9,674.6M | -111 years (-4.3%), -$1,869.7M (-16.2%) |
| club_holds | 2,542 | 10,306.4M | -52 years (-2.0%), -$1,237.9M (-10.7%) |

- 101 players have an option year still ahead of the year in force: 62 option years are team,
  45 player, 11 vesting (118 entries across 108 players; 7 players have it on the year in force).
- Control years (his formula) change for 93 of the 101 under `guaranteed` (-1 for 83, -2 for 10) and for
  42 under `club_holds`. No player drops to 0 guaranteed years.
- Example: Jonah Clause (hitter, id 55906, 32, 10.1 service years): schedule $35M, $35M, $40M, today
  Owed $110.0M and 3 control years; two player options (years 2 and 3 of the remaining schedule) leave
  $35.0M and 1 guaranteed year.
- Stale contracts (separate defect, now visible): 10 priced players have `SalaryStartYr` of 2041-2043 in
  a 2044 league, all `is_major = 0` (minor-league deals left over from earlier seasons). Their `Price`
  is the old salary. The new key lets the app flag them; nothing is changed.

## 6. New record keys (all optional)

| Key | Type | Source | Example (SSB, player 51213) |
|---|---|---|---|
| `SalaryStartYr` | int | `season_year + current_year`; set where `SalarySchedule` is set | `2044` |
| `ContractOptions` | list | flags + slot buyout; `yr` = `season_year + idx`, `i` = index into `SalarySchedule` | `[{"yr":2046,"i":2,"type":"team","slot":"last","buyout":1700000}]` |
| `ContractBuyouts` | dict | the two raw buyout fields, only when either is above 0 | `{"last":1700000,"next_last":1900000}` |
| `ContractExt` | dict | `/contractextension` row | `{"yr":2047,"years":2,"salaries":[...],"after_base":true}` |

Reply without option columns: option keys stay unset (never `[]`). Reply without the extension
endpoint: no `ContractExt`. Existing keys: byte-identical (section 8).

## 7. Choices

- 🟢 from data: option positions (`years-1`, `years-2`), calendar year arithmetic, extension alignment,
  buyout-by-slot, "an option on the year in force is decided" (the player is playing it).
- 🟡 borrowed: none.
- 🔵 assumptions: (a) a declined option ends the deal, so years after it are dropped in `guaranteed`;
  in the saved data a `next_last` flag never appears without a `last` flag, so this reading and
  "drop only the optioned years" give the same numbers; (b) only team options add a buyout.

### Ported from `contract_projection.py`, and what was left out (hard-coded rule or fetched)

| Piece in `contract_projection.py` | Kind | Decision |
|---|---|---|
| `resolve_contract_year` (salary, option type, buyout for a calendar year, incl. extension) | arithmetic on StatsPlus fields | ported as `resolve_year` |
| `detect_contract_year` (mode of `season_year + current_year`) | arithmetic on StatsPlus fields | ported |
| `DAYS_PER_SEASON = 172` | hard-coded in ours, hard-coded in his `SVC_YEAR_DAYS` (comment says measured) | not hard-coded here: `roster_clock.service_year_days` measures it from `/players` rows. SSB: exactly 172 at the major-league level, 0 violations in 1,944 rows |
| `detect_season_day`, `detect_limbo` | arithmetic on service days | ported in `roster_clock.py` (waivers_service.md) |
| Super Two: top 22% of the 2-year class, 86-day minimum, 130-day fallback | OOTP rule hard-coded in ours | left out. StatsPlus has no Super Two field |
| Free agency at 6 service years, arbitration at 3 (`6 - mlb_years`) | OOTP rule hard-coded in ours; also in his `serviceTime.js` (`FA_SERVICE_YEARS`, `ARB_SERVICE_YEARS`) | left out of the new code; his constants are untouched |
| `calc_r5_projection` (5 or 4 years by signing age 18, default age 19) | OOTP rule hard-coded in ours | left out. `/players` has `years_protected_from_rule_5`; that belongs to the roster-management item |
| `calc_mlfa` (7 years) | OOTP rule hard-coded in ours | left out |
| `get_options_info` (3 option years) | OOTP rule hard-coded in ours; input `opt` is from `org.csv` | left out |
| `parse_contract_status`, `project_year_status` | built on the rules above and on `org.csv` text (`YL`) | left out |
| `salary_report.py` annotations ((A) arbitration projection, (O) opt-out, (R) retained, italics = not guaranteed) | StatsPlus HTML, one page per team | not ported: ~30 extra page requests per run, and no HTML sample is saved to test against. The report is where opt-outs and arbitration projections live; `/contract` shows neither |

## 8. Verified vs inferred

Verified by running: all counts and dollar figures above; that the regenerated SSB files match the
committed ones on every existing key (13,991 players, 0 values changed, 0 keys lost) with only new keys
added; 42 unit tests (this item and the waiver item) pass offline.
Inferred: the `/contractextension` header; the meaning of buyouts without a flag; that the six unflagged
report option cells are cleared flags; the proposal's 🔵 assumptions.

## 9. Gated proposal (for the user to decide)

Not applied. Option A: keep Owed and control as they are and show the new keys only (a badge "option
year 2046 (team, $1.7M buyout)"). Option B: switch Owed and control to `guaranteed` and show `as_is` as
"if all options run". Option C: show both lines everywhere Owed is shown. Recommendation: A first
(Phase 4, no number changes), then C once the unflagged-buyout and missing-flag questions are answered
by one live look at five contracts in OOTP. B changes 101 players' control years and the multi-year
surplus in `marketValue.js`, so it needs the same sign-off as any pricing constant.
