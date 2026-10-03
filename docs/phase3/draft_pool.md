# Phase 3: draft pool from StatsPlus (audit, written before the code)

Branch `phase3/draftpool`. Item: the plan's "Draft pool" row. Legend: 🟢 measured from saved data,
🟡 borrowed from our code or notes (provenance given), 🔵 deliberate assumption, ⚠ unverified.

## 0. Consequence

SSB has no draft board today because `draft.py` looks for an OOTP draft-pool export in the OOTP save
folder, and SSB has no `ootp_save` setting (OOTP is not installed on this Mac). The board therefore
stops at "No draft pool for SSB" and writes no `hitters_draft.json` / `pitchers_draft.json`. The
ratings of every SSB draft-eligible amateur are already in the ratings pull, so the only missing
piece is the list of player IDs in this year's class. Our dashboard gets that list from StatsPlus
`<api>/draftpool/`. The change: his client gets `fetch_draftpool`, and `draft.py` asks StatsPlus
first and the OOTP export second.

One thing could not be settled offline: **the real reply of `/draftpool/` has never been saved
anywhere on this machine** (section 2). The shape is built from our parser and tested against a
fixture; it is marked unverified and one live request validates it (section 9 of the final report).

## 1. What his flow does today (read this session)

| Step | Where | What it does |
|---|---|---|
| Pool source | `ingest/draft.py` `_pool_groups`, `DEFAULT_CSV` | Looks for OOTP's draft-pool CSV(s) under `<ootp save>/import_export`. A league without `ootp_save` in settings gets no path at all (SSB: `settings.local.json` has none). |
| No-export fallback | `draft.py` `API_POOL_FALLBACK = {"BLM"}` | BLM only: `/players` `draft_eligible == "1"`. His docstring says this flag marks the whole amateur pool, future classes included. |
| Ratings | `statsplus_<slug>.json` (the ratings pull, left by `refresh.py`) | Rows whose `ID` is in the pool are translated (`translate_rows`) and projected by `run_hitters` / `run_pitchers`. No extra request. |
| Extras | `CSV_EXTRA = DEM, Sign, SctAcc, NAT, Inf` | Copied verbatim from the export rows. |
| Picks | `S.fetch_draft(fresh=True)` (`/draft`) | Live pick list. Refusal stops the run (exit 3); an empty list while the saved list holds picks of this pool keeps the saved list. |
| Refusals | `statsplus.StatsPlusRefused`, `_stop()` | Typed (`token_invalid`, `token_expired`, `login_required`, `daily_limit`, `too_soon`, `not_enabled`, `blocked`, `not_data`). |

His docstring claim "StatsPlus has no list of this year's draft class" is true only of `/players`
and `/draft`. It does not mention `/draftpool/`.

## 2. What ours does and what is known about `/draftpool/`

`model/src/draftpool.py` (commit 1da1c47):

- `fetch_draftpool(url)` does `GET <api>/draftpool/`, no token, parses CSV, reads only the `ID`
  column, returns `list[int]`. Any failure becomes `[]` plus a printed warning.
- The docstring says the header is `"ID","Player Name"`, "for the current or most recently completed
  draft". The only test fixture is `b'"ID","Player Name"\n"12","A Guy"\n"34","B Guy"\n'`
  (`model/tests/test_draftpool.py:194`), which our own code wrote. 🟡
- The year comes from `/date`. Ratings come from dated scout dumps in `leagues/<slug>/ratings/`,
  mapped to OOTP export columns. His flow needs none of that mapping (his projections already read
  the pull's own column names).
- `players.py:397-419`: a hand-exported `draft<YYYY>.csv` wins over the API; the API is used only when
  no draft CSV exists.

What I searched for, to find a saved reply: every `*draftpool*` file on disk, `ootp-dashboard`
(`leagues/SSB/.statsplus_cache.json.gz` keys are `contracts`, `players`, `salary_reports` only), his
`.cache/sp/ssb/` (`contract`, `players`, `teams` only), `analysis/statsplus-automation` (probes,
findings, `output/SSB`). **No saved `/draftpool/` reply exists.** `~/Downloads/draftpool.csv` is a
2021 file with a different layout (rating columns, 1,351 rows); it is not this endpoint.

⚠ Conflicting evidence on the shape, both unverified:

1. Ours says tokenless, columns `ID`, `Player Name`.
2. `analysis/statsplus-automation/STATSPLUS_API_REQUEST.md` section 3 records "Draft demands |
   `/draftpool?token=`" as a field the StatsPlus author added after our request. That implies the
   endpoint may be token-gated now and may carry draft-demand columns (our export columns `DEM` /
   `Sign`). The note gives no column names.

Design consequence: the new fetcher sends his automatic league token (as every request of his
client does, including `/date`; a token sent to an endpoint that does not need it is harmless), needs
only the `ID` column, keeps every other column verbatim, and prints the extra column names once so the
live validation shows what StatsPlus really sends. No extra column is mapped to a board field under a
guessed name.

## 3. Source fields

### 3.1 `/draftpool/` (⚠ shape unverified)

| Field | Meaning | Status |
|---|---|---|
| `ID` | player ID, joins to the ratings pull `ID` and `/players` `ID` | required column; the fetcher refuses a reply without it (`not_data`) |
| `Player Name` | display name | read when present (one WARNING when absent, his convention for optional columns) |
| anything else | possibly draft demands (see 2) | kept verbatim in the fetched row; copied to the record only when the column is already named like a board field (`DEM`, `Sign`, `SctAcc`, `NAT`, `Inf`) |

### 3.2 Ratings pull (`.cache/statsplus_ssb.json`, game date 2044-05-02) 🟢

13,991 rows, one per player, `ID` a string. Key columns the draft board reads: the rating columns
translated by `translate_rows`, `Pos`, `Age`, `Org`, `LgLvl`, `Acc` (scout accuracy code VH/H/A/L),
`Ovr`, `Pot`. Amateurs are in it: 4,616 rows have `Org == "0"`.

### 3.3 `/players` (`.cache/sp/ssb/players.json.gz`, 77,487 rows, game date 2044-05-02) 🟢

`draft_eligible`: 2,944 rows are `"1"`; 2,909 of those are in the ratings pull (35 are absent: ages
39-45 and similar, all unscouted). `draft_year` is `"0"` for all 2,944 (so `draft_year` cannot split
classes, same finding as our `API_PROBE_NEGATIVES.md` negative #1).

## 4. Does the ratings pull already hold the pool's ratings? 🟢 yes

The two hand-exported classes in ours (`leagues/SSB/csv/players/draft2044.csv`, 573 rows;
`draft2045.csv`, 302 rows; disjoint, 875 IDs):

| Check | draft2044 | draft2045 |
|---|---|---|
| IDs in the ratings pull | 573 / 573 | 302 / 302 |
| IDs in `/players` with `draft_eligible == "1"` | 573 / 573 | 302 / 302 |
| their `Org` / `LgLvl` in the pull | all `0` / `0` | all `0` / `0` |

So no extra ratings request is needed. The committed SSB `hitters.json` / `pitchers.json` already
carry 1,301 + 1,608 = 2,909 amateurs at `Lev == "AMA"`, which equals the 2,909 `draft_eligible` rows
in the pull; the draft board re-projects the class members from the same pull.

The flag is not the class: 2,944 flagged versus 875 in the two exports. The other 2,069 are not in either
export; their ages run 14-23 (388 are 16, 332 are 15, 293 are 17, 267 are 20, 224 are 21), plus 9 aged 45
and 7 aged 41 with no ratings in the pull. Which of them belong to later classes is not something the
flag says. That is why his docstring distrusts the flag, and it is why `draft_eligible` must not become the
primary source for SSB; `/draftpool/` (a list of the class) is.

Age check on the hand exports: for the same ID the pull's age is 1 year higher for 354 + 187
players and 2 years higher for 219 + 115 players. The hand exports are older than the 2044-05-02 pull,
so the SSB class in the exports is stale; a fresh `/draftpool/` read at the pull's date is the
current class.

## 5. Decisions and their classification

| # | Choice | Class | Why |
|---|---|---|---|
| 1 | Pool IDs come from `/draftpool/`; nothing is derived from age, `draft_year` or any rule we write | 🟢 / rule 2 | Standing rule: eligibility comes from StatsPlus. |
| 2 | `fetch_draftpool(base, *, cache, fresh, token)` follows `fetch_draft` / `fetch_teams`: `_fetch_csv`, `COLUMNS["draftpool"] = (("ID",), ("Player Name",))`, `allow_empty=True` | 🟢 his pattern | Typed refusals, missing-column WARNING, `OffSiteError`, token handling come with it unchanged. |
| 3 | `draft.py` reads the pool with `cache=True` (date-gated, 6 h) | 🔵 | The class list only changes with the in-game date, and a reply cached earlier the same day keeps the full class while picks are made (`/draft` is still read fresh for picks). Costs one request per in-game day at most, plus the `/date` request he already makes. |
| 4 | Trailing slash `/draftpool/` | 🟡 ours (the research note writes `/draftpool?token=`) | ⚠ unverified; his `_StayOnSite` follows a redirect on the same site either way. |
| 5 | Precedence: StatsPlus first; export second; BLM `draft_eligible` flag last (unchanged) | 🔵 | Plan says StatsPlus primary. When both exist the export only supplies its extras (`DEM`, `Sign`, `NAT`, `Inf`, `SctAcc`) for IDs that are in the StatsPlus pool. `--pool-source export` restores the old order for a league whose export is trusted. |
| 6 | A refusal or network failure of `/draftpool/` with an export present: warn, use the export. Without an export: a refusal stops with exit 3 (existing `_stop`), a network failure falls through to the old "No draft pool" message | 🔵 | Matches his rule that a refusal never rebuilds silently; the export is a deliberate local choice, not a stale cache. |
| 7 | Empty `/draftpool/` reply is "no pool from StatsPlus", not an error | 🔵 | Same as `/draft` before a draft. |
| 8 | Hitter / pitcher tag for API rows comes from the pull's own `Pos` (his existing fallback in `is_pit`) | 🟢 his code | The API list has no position. |

## 6. What was built

- `ingest/statsplus.py`: `fetch_draftpool(base, *, cache, fresh, token)` plus `COLUMNS["draftpool"]` and one line in
  the endpoint list. Nothing else in the client changed; `fetch_all` (the scheduled bulk fetch) does not
  call it, so no pull gains a request.
- `ingest/draft.py`: `_api_pool`, `_resolve_pool`, `--pool-source auto|statsplus|export`, the module docstring,
  and the "No draft pool" text. `main()` changed in three places (the source line, the labels print, the
  closing hint). Dispersal mode is untouched.
- `tools/tests/test_draft_pool.py` (38 tests) with fixtures in `tools/tests/fixtures/draft_pool/`.

Failure matrix (tested): StatsPlus answers -> its list is the class. Empty list -> export, else the old "No
draft pool" skip. Typed refusal -> export with a printed warning; without an export, exit 3 (BLM goes on to
its flag, which stops by itself if the refusal is real). Network error or off-site redirect -> export, else
the old skip. The token is never in a message (test: a refusal body that echoes it).

## 7. Offline run for SSB (measured this session; pool IDs = our hand-exported classes as a stand-in)

`/draftpool/` was not called. The pool was set to the IDs of `draft2044.csv` / `draft2045.csv`, the ratings
are the saved 2026-10-02 pull (game date 2044-05-02), `draft.py --league SSB --slug ssb --calib BLM` ran
with the fetches replaced, writing to a scratch folder.

| | 2044 class | 2045 class |
|---|---|---|
| pool IDs | 573 | 302 |
| matched in the pull | 573 | 302 |
| his board: hitters + pitchers | 263 + 310 | 128 + 174 |
| our dashboard board (`Draft 2044` / `Draft 2045` rows) | 263 + 310 | 128 + 174 |
| same player IDs on both | yes | yes |
| Spearman rank correlation, hitters (his `MAX WAA P` vs our `prospect.waa.max`) | 0.919 (n=263) | 0.894 (n=128) |
| same for starters (his `WAP` vs our `prospect.sp.waa`) | 0.932 (n=218) | 0.901 (n=136) |
| overlap of the top 25, hitters / starters | 19 / 20 | 18 / 20 |

n for the pitchers is lower because only rows with a numeric `WAP` are compared (218 of 310, 136 of 174).
Top hitters, 2044, his board: Joe Brown 3.0, Jose Carrillo 3.0, Bob Moreno 2.8, Juan Bravo 2.6, Tony Logan
2.6; ours: Bob Moreno 4.8, Joe Brown 4.4, Tony Logan 3.8, Juan Bravo 3.4, Jose Carrillo 3.0. Top starters,
2044: Steve Madsen and Mike Rowan lead on both boards. The orderings agree closely; the levels differ (ours
is higher at the top). The two boards differ in three inputs at once, so the table is a sanity check, not a
referee: ratings date (his 2044-05-02, ours 2043-12-14), scale of the WAA measure, and the calibration (his
is priced on the BLM basis for SSB; ours on the BLM calibration through our own chain). I did not separate them.

## 8. Flags still open

1. ⚠ `/draftpool/` reply shape, token requirement and trailing slash (section 2). One live request settles
   all three.
2. ⚠ Which class `/draftpool/` returns on a given date. Our hand exports carry two classes (573 and 302);
   if the endpoint returns the current class only, the 2045 board is not reachable from it.
3. `draft_eligible` is never used for SSB (only for BLM, unchanged).
4. 🔵 Precedence, the 6-hour date-keyed cache, and exit 3 for a refused TGS/SSB pool with no export are
   decisions for the user (final report).
5. `tools/tasks.py` text still says the board needs an OOTP export (`draft.banner`, `ratings.tgs_draft`,
   `ratings.blm_draft`, the Update Draft Board description). I left the task definitions alone to avoid a
   conflict with other Phase 3 edits; the wording is stale, the behaviour is not.
6. Draft demands (`DEM`, `Sign`): SSB boards built from StatsPlus have none unless the reply carries a column
   with exactly that name. The app reads `p.DEM` in `DraftBoardPage.jsx:48` (the Impossible filter, inert when
   absent) and `MockDraftPage.jsx:363` (blank cell).
