# Phase 3: StatsPlus team salary reports (audit)

Branch `phase3/salary`. Written before the code. Every count below was produced by running a
script over saved data (the dashboard's saved parsed reports and the fork's saved `/contract`,
`/teams` and `/players` replies); the reproducible form is
`python tgs-viz/ingest/salary_report.py --saved <statsplus_cache.json.gz>` (section 8).

## Summary

- The report pages are the only place the league shows OOTP's own arbitration projections
  (cells marked "(A)" and "(A*)" / "(A#)"), opt-outs ("(O)") and retained salary ("(R)").
  `/contract` carries none of the three. On the saved SSB snapshot 849 of the 1,134 players on
  an MLB team page carry at least one arbitration projection, and 22 cells are opt-outs.
- This change reads one page per MLB team (28 for SSB) through his `statsplus.py` rules and
  attaches the parsed result to the pull's records as new keys. No existing key changes.
- The cost is 28 page requests on the first pull of an in-game day, and 0 on every later pull
  that day (the date-keyed cache). Pages are read one at a time with a short pause between them.
- Two things cannot be settled offline and need one live page read: whether
  `https://statsplus.net/<slug>/reports/news/html/teams/team_<id>_player_salary_report.html` is
  served on the host his client uses (the dashboard's saved reports came from
  `https://atl-01.statsplus.net/ssb/`), and that the real HTML still matches the parser. No raw
  page exists anywhere in either project; only the dashboard's parsed output.

## 1. What the dashboard does today (read)

`model/src/salary_report.py` (231 lines):

1. `fetch_all_teams` reads `/teams/`, `fetch_all_salary_reports` keeps the teams whose
   "Name Nickname" is in `ballparks.csv`, and fetches the pages with `ThreadPoolExecutor(max_workers=6)`:
   six requests in flight, no cache, no token, no staleness rule, no typed refusals. This is the
   behavior that is not allowed here.
2. Page URL: `{report_base}/reports/news/html/teams/team_{team_id}_player_salary_report.html`,
   `report_base` = the league URL with a trailing `/api` removed (`https://atl-01.statsplus.net/ssb`).
3. Parse (regexes, no HTML library): year columns from the `<th>` cells that read `YYYY`; one table
   row per player that has a `.../player_<id>.html` link; the first `<td>` is the position; salary
   cells start at the fourth `<td>`; cell `i` is the year column `i`.
4. Cell reading: empty or a dash = `fa`; text `MiLC` = `milc`; otherwise the trailing annotation picks
   the type, the dollar text (`$3.2M`, `$804K`) is the salary, and an `<i>` or `<em>` tag anywhere in the
   cell means "not guaranteed".
5. Result `{playerId: {name, pos, years: {year: {salary, type, guaranteed}}}}`, cached by `main.py` in
   `leagues/<slug>/.statsplus_cache.json.gz` under `salary_reports` for one game date.

How the dashboard uses it (`contract_projection.py:431-500`, called from `export.py:1868,1889`): for the
Contract/Control table it looks up the player's cell for each future year and prints
`Arb`, `Arb?` (uncertain), `Team Opt`, `Player Opt`, `Vest Opt`, `Opt-out`, `Retained`, `Signed`,
`MiLB`, `MiLC` or `FA` with the page's salary. In the offseason, once `/contract` has rolled to the
next year, the contract feed wins for years it covers and the report only supplies years beyond it
and the `milb` / `milc` level markers. Nothing in the dashboard computes an arbitration salary: the
number shown is the page's.

## 2. Source fields (the saved parsed reports)

Saved file: `leagues/SSB/.statsplus_cache.json.gz`, `fetched_at` 2026-10-04, game date **2044-05-09**,
`salary_reports` holds **1,134 players** (the task text said 1,233 / 2043-12-14: that was the older
copy; the file was re-saved since). Every player has 10 year cells, 2044 to 2053. All 1,134 ids are in
the fork's saved ratings pull. The pages cover players on the 28 MLB clubs' lists only (about 40 per
club), not the whole organisation.

Cell types observed (count of cells over 1,134 players x 10 years = 11,340):

| type | cells | page text (from the parser) | salary present | italic (not guaranteed) |
|---|---|---|---|---|
| `fa` | 6,313 | empty or a dash | never | n/a |
| `signed` | 1,045 | `$3.2M` | 1,022 of 1,045 | 22 |
| `arb` | 2,225 | `$4.6M (A)` | all | all |
| `arb_uncertain` | 650 | `$1.7M (A*)` or `(A#)` | all | all |
| `milb` | 963 | `$571K (*)` | all | all |
| `milc` | 22 | `MiLC` | never | n/a |
| `team_option` | 53 | `(T)` | all | none |
| `player_option` | 44 | `(P)` | all | none |
| `vesting_option` | 3 | `(V)` | all | none |
| `opt_out` | 22 | `(O)` | all | none |
| `retained` | 0 | `(R)` | n/a | n/a |

Players (of 1,134) with at least one cell of the type: `arb` 849, `arb_uncertain` 495 (all 495 also
have a certain `arb` cell, so 849 players carry an arbitration projection of either kind); `team_option`
51, `player_option` 37, `vesting_option` 3; `opt_out` 22 (one cell each); `milb` 573; `milc` 15;
**`retained` 0**, so the `(R)` handling has never been exercised on real data and is the least certain
part of the parser. Each arbitration player has 1 to 5 arbitration cells (1: 74 players, 2: 75, 3: 213,
4: 423, 5: 64). The first arbitration cell is 1, 2, 3 or 4 years after the game year for 318, 364, 166
and 1 players; it is a certain `(A)` for 362 players and an uncertain one for 487.

### Checks against `/contract` (verified by running, fork's saved reply 2044-05-02)

- **Page dollars are rounded.** Compare the page salary with the `/contract` salary of the same
  calendar year (`season_year + i`) for cells that fall inside the contract's years: 1,015 `signed`
  cells differ by at most **$50,000**; 52 team-option cells by at most $30,000; 21 opt-out, 42
  player-option and 3 vesting cells match exactly. Of the 4,982 cells that carry a salary, the 3,624 at
  or above $1M are all multiples of $100,000 and the 1,358 below $1M are all multiples of $1,000. So the
  page is rounded to $0.1M above $1M. An arbitration projection read from the page therefore carries up
  to $50,000 of rounding: 0.2% of a $25M salary, 6% of a $0.8M one. (Different saves: the report is
  2044-05-09, the contract reply 2044-05-02; 11 cells fall in years the contract row does not cover,
  such as extensions, and are not in these counts.)
- **Arbitration cells have no contract salary** (2,225 + 650 arbitration cells: the `/contract` row has
  no salary for that year in every case). This is the point: the projection exists only on the page.

### Unparsed cells (found while auditing)

23 `signed` cells have no salary (22 italic, 1 not). The dashboard's parser labels any text it cannot
read as `signed`. They sit in the year right after the in-force year for players who are arbitration
eligible next (`2044 signed $2.6M, 2045 ???, 2046 arb $4.6M`). The text is not saved, so what they say
is unknown. This port labels them `unparsed` and keeps up to 40 characters of the raw text
(`raw`), so one live page read shows what they are. It does not call them signed.

## 3. What the fork's ingest does today

Nothing: `refresh.py` reads `/teams`, `/contract`, `/players` (+ `/contractextension` from the contracts
item), no HTML page. `docs/phase3/contracts.md` section 7 recorded the report as "not ported: ~30
requests per run, no HTML sample". The user has since decided the pages must be read.

His client rules that apply (read, `statsplus.py`):

- `_open(url, token=, stay_on=)`: one request, typed refusals (`StatsPlusRefused`), `OffSiteError`
  when `stay_on` is given and the host or a redirect leaves the site, token redacted from every message.
- `_cached(base, url, fetch, cache, fresh)`: key = (url, the league's `/date`), 6-hour age limit,
  files in `.cache/sp/<slug>/`. `cache=True` reuses; `fresh=True` fetches and saves.
- `site_url(url, base)`: host is statsplus.net or a subdomain of it, same port, https stays https.
- The token: `_pick_token` sends the league token on its own only to a URL whose path has
  `<slug>/api`. A report URL has no `/api`, so none is added by default; this work also passes
  `token=False` so none can be added.

## 4. Design

- **Module** `tgs-viz/ingest/salary_report.py`, stdlib only, new file; `statsplus.py` is not edited.
  It uses `statsplus._open`, `_cached`, `site_url`, `_refused_reply`, `StatsPlusRefused`, `redact`.
- **Host:** `report_base` = the API base with `/api` removed, i.e. `https://statsplus.net/<slug>`.
  Every request goes through `_open(url, token=False, stay_on=<api base>)`, so a host or redirect off
  statsplus.net (or off the test mock) raises `OffSiteError` before anything is sent. Subdomains such
  as `atl-01.statsplus.net` are accepted by `site_url`; a caller can pass `report_base=` to use one.
- **Token:** none. The dashboard sends none and its saved reports are real, so the pages are public
  (inferred from that, not seen; if a page asks for a login the reply is a typed `login_required`).
- **Teams:** the ids of the MLB clubs come from data the pull already holds, no extra request: the
  distinct `Org` of the ratings rows whose `Lev` is `MLB` (SSB: 28 ids, 31-60 except 40, 41), kept
  only when `/teams` lists the id with `Parent Team ID` 0. Checked on the saved pull: 28 of 28 pass.
  `/teams` itself has no level column (columns `ID, Name, Nickname, Parent Team ID`; 80 rows have
  parent 0, including 24 All-Star and foreign clubs), so it cannot give the MLB set alone.
- **Load:** pages go through `_cached(cache=True)`: a page is read at most once per team per in-game
  day and at most 6 hours old, also on live pulls (which pass `fresh=True` for the core feeds). One
  request at a time, a 0.5-second pause before each live request after the first (🔵 courtesy value, not
  derived from anything; `PAGE_GAP_S`). The raw HTML is what is cached, so a parser fix needs no new
  requests. A refusal (any `StatsPlusRefused`) or an off-site error stops the run at once; two failures in
  a row (404, timeout) also stop it, so a wrong path costs 2 requests, not 28.
- **Cached pages are validated first:** a reply is cached only if it has year column headers; anything
  else (login page, refusal text, error page) is raised as a typed refusal and nothing is saved.
- **Pull:** one block in `refresh.py` after the contract-terms block, never fatal, off with
  `--no-salary-reports`. It prints pages fetched vs reused.

## 5. New record keys (all optional; absent = not on a team page, or the reports were not read)

| Key | Type | Meaning | Example (SSB 2044-05-09, id 59554) |
|---|---|---|---|
| `SalaryReport` | object | `{year: cell}`, one entry per year the page shows something other than FA. `cell` = `{salary, type, guaranteed, ann?, raw?}`: `salary` dollars as printed on the page (rounded to $0.1M above $1M) or null; `type` one of `signed arb arb_uncertain milb milc team_option player_option vesting_option opt_out retained unparsed`; `guaranteed` = the cell is not italic; `ann` the page's annotation without parentheses (`A`, `A*`, `A#`, `*`, `T`, `P`, `V`, `O`, `R`), only on annotated cells; `raw` the unreadable text, only for `unparsed` | `{"2044":{"salary":2600000,"type":"signed","guaranteed":true},"2045":{"salary":null,"type":"unparsed","guaranteed":false,"raw":"..."},"2046":{"salary":4600000,"type":"arb","guaranteed":false,"ann":"A"},...}` |
| `SalaryReportSpan` | [int, int] | first and last year columns of the page. A year inside the span with no entry in `SalaryReport` is shown as FA | `[2044, 2053]` |
| `ArbProjection` | object | the page's first arbitration cell: `{yr, salary, uncertain, ann, n}`; `uncertain` is true for `(A*)` and `(A#)`; `n` = how many arbitration cells (either kind) the page shows for the player. No arithmetic beyond picking the earliest year | `{"yr":2046,"salary":4600000,"uncertain":false,"ann":"A","n":3}` |
| `OptOutYrs` | [int] | years whose cell is `(O)`, only when there is one | `[2047]` (id 63066) |
| `RetainedYrs` | [int] | years whose cell is `(R)`, only when there is one | none in the saved data |

`FA` cells are left out (6,313 of the 11,340 saved cells) to keep the files small. Measured on the
offline SSB rebuild: the keys add 265 KB to `hitters.json` (48.7 MB, 580 players) and 256 KB to
`pitchers.json` (40.1 MB, 554 players), the same again for the two My Park copies: about 1.0 MB over
the four files (1.2%). Nothing is derived from the page: no arbitration
formula, no Super Two, no service-time rule. What `(A*)` and `(A#)` mean is OOTP's (the dashboard
calls both "uncertain"); the raw mark is kept in `ann`.

Phase 4 use: Owed / control years can read `SalaryReport` for years `/contract` has no salary
for (arbitration years, options) and `OptOutYrs` for the player's exit right; the Roster Planner can
read `ArbProjection` as next year's pay for a player not yet signed through it.
**Frame caution:** in the offseason the page is anchored to the completed season while `/contract`
has already rolled (the dashboard documents this at `contract_projection.py:437`). `SalaryReportSpan[0]`
vs `SalaryStartYr` tells the app which frame it is looking at.

## 6. Choices

- 🟢 from data: the URL, the cell types, the rounding bound ($50k, checked against 1,015 contract
  salaries), the MLB team set, the key set.
- 🟡 borrowed: the parser regexes and the annotation table are the dashboard's, which produced the
  saved results above from real pages. One change: the italic test is `<(?:i|em)` followed by a space or
  `>` (the dashboard's `<[ie][m>]` also fires on `<img` and misses `<i class=...>`). On the saved
  results this cannot be compared (no HTML); it is the only deliberate difference.
- 🔵 assumptions: no token is needed; `statsplus.net/<slug>/reports/...` serves the page like the
  `atl-01` host does; the 0.5 s pause; "not italic = guaranteed" (the dashboard's reading; consistent with
  the data: every arb / milb cell is italic, every option and opt-out cell is not).

## 7. Verified vs inferred

Verified by running: all counts in section 2; the 28-team set; the $50k bound; the cell-type table; the
cell shapes `ArbProjection` is built from (example players); 48 offline tests
(`tgs-viz/tools/tests/test_salary_report.py`); and an offline end-to-end pull: `refresh.py --statsplus
--league SSB --calib BLM --from-cache` against a mock StatsPlus on 127.0.0.1 that served the saved
`/teams`, `/contract`, `/players` replies and 28 pages rendered from the dashboard's saved parsed
reports. Results: first run `28/28 team pages (28 fetched, 0 reused); 1134 players, 1134 records carry
SalaryReport`, with exactly 28 page requests, none carrying a token (the data endpoints did carry the
test token, as designed); second run `28/28 (0 fetched, 28 reused)` with 0 page requests (only the
one `/date` read); `--no-salary-reports` leaves the keys off. Comparing the run with and without the
reports: 0 existing values changed in 6,866 hitter and 7,125 pitcher records. The mock pages were
rendered by our own code, so this proves the plumbing, not the HTML.
Inferred: the HTML (no page saved: the parser is tested on a synthetic page built from the parser's own
regexes, marked UNVERIFIED); that the default host serves the page; that no token is needed; what the 23
unparsed cells and `(A*)` vs `(A#)` say; `(R)` (zero cells in the saved data).

## 8. Needs a live request

One team page, one request: `GET https://statsplus.net/ssb/reports/news/html/teams/team_32_player_salary_report.html`
(Atlanta, id 32, SSB's own club). No token. It confirms: the host serves it; the HTML parses (years,
players, `ann`); what the `unparsed` cells' `raw` text is; the real shape of `(R)` and `(A#)` cells if
any appear. Then one pull on a fresh in-game day costs 28 requests; the next pull the same day costs 0.
If that URL answers 404 or "not data", try the dashboard's host by passing
`report_base="https://atl-01.statsplus.net/ssb"` (two lines in `fetch_reports`), and tell me which.

## 9. Decisions for the user

1. **Default on, 28 requests per new in-game day.** `--no-salary-reports` skips it. Recommendation: on;
   the cost is one burst per game day, 0 after.
2. **Report host.** Default `https://statsplus.net/<slug>/reports/...` (his client's host); the
   dashboard used `https://atl-01.statsplus.net/<slug>/`. Needs the one live page read in section 8.
3. **Phase 4 frame handling.** In the offseason the page and `/contract` disagree on the year; the app
   should compare `SalaryReportSpan[0]` with `SalaryStartYr` before mixing them.
4. **Not wired:** nothing in the app reads the new keys; his Owed / control logic is unchanged.
