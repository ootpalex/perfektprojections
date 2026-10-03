# Phase 2 row 12 - engine-version boundary (audit, written before the code)

Status: tooling guard. It changes no projection number. Wired in, not gated.

## What it is for

A league that moved to a new OOTP engine (SSB: OOTP 26 to 27 at season 2043) has
seasons on two engines. Data from the old engine must not feed the new engine's
calibration constants. Ours handles this with `engineFirstSeason` in
`leagues/<LG>/league.json`, set by `model/tools/convert_league_version.py` and
enforced in `model/src/metadata.py` (`_enforce_engine_boundary`, ~:538-567: seasons before
the boundary are excluded; a missing boundary for a version that needs one stops the
build). His fork had no such concept: `ingest/metadata_inputs.py` builds a metadata
season from whatever season the in-game date (or `--year`) names.

## Design

- New optional league key in settings: `engine_first_season`, one whole year
  (e.g. 2043), meaning "the first season played on this league's configured
  `ootp_version`". Ours is a dict keyed by OOTP version because one league.json
  can carry several versions; his settings already hold ONE `ootp_version` per
  league, so a bare year is enough and cannot disagree with it.
- `settings.py` validates it like his other league fields (plain-words message
  naming the key) and gets a reader `engine_first_season(league_id)`.
- `metadata_inputs.py` refuses, with a typed `sys.exit` message in his style
  (exit 1, "a stop with a message"), to build a season before the boundary.
  The check runs (a) before ANY request when `--year` is given and (b) after the
  one `/date` request but before `/teams` and the stat feeds when the season comes
  from the in-game date.
- `tools/new_league.py`: the New League spec accepts an optional
  `engine_first_season` for statsplus / local_export leagues, checks it, and writes
  it into the pending settings entry.
- The Control page settings view: see "Control page" below.

## Input trace

| Input | Tag | Provenance |
|---|---|---|
| BLM boundary (evidence only, not wired) | 🟡 | ours: BLM-ATL / BLM-CIN `engineFirstSeason["27"] = 2058`; same-league identity with his BLM is inferred |
| SSB boundary = 2043 | 🟢 | `leagues/SSB/league.json` `engineFirstSeason["27"] = 2043` in ootp-dashboard; SSB metadata 2041/2042 are OOTP 26, only 2043 is OOTP 27 (brief, read from disk) |
| BLM / TGS / RG / DEV boundary | 🔵 | unset. No boundary is known for them, so no refusal; behavior is unchanged. Not invented. |
| Valid range of the year (1000..9999) | 🔵 | only rejects typos such as 43 or "2043"; any real OOTP year passes |
| Which seasons the guard covers | 🔵 | the season being BUILT. The paste-detection lookups of earlier seasons (`other_seasons`) stay unfiltered: they only name a wrong paste's season, never feed a constant |
| Semantics "season >= boundary is allowed" | 🔵 | same as ours (`year >= boundary` kept) |

No borrowed numeric constant enters the code. Nothing computed from data.

## Flags and resolutions

1. `metadata_inputs.py` only accepts `--league TGS|BLM` (`LEAGUE_DIRS`), so SSB
   cannot be built by it today. The key is still stored for SSB so that
   (a) doctor can show it and (b) the guard is ready the day a basis-less SSB
   metadata build exists. Resolved: documented, no behavior change.
2. Without `--year` the season comes from the in-game date, which needs one
   `/date` request (the same request the script already makes first). Refusing
   earlier is impossible without that request. Resolved: the check sits between
   `/date` and `/teams`; the heavy feeds are never asked.
3. The key must not break leagues that lack it. Resolved: absent = no check;
   test asserts the unconfigured path reaches the fetch.
4. Control page: `control/http.js` ALLOWED_KEYS is a whitelist for what the
   Setup form may PATCH; it does not reject extra keys that are already in the
   settings file, and `SettingsForm` reads only named fields. So the new key is
   tolerated and, deliberately, not editable from the form (it is a one-time
   boundary, set in settings.local.json). Resolved: no JS change; Node control
   tests run unchanged.

## What to add to settings.local.json (not done: main checkout is off limits)

Under `"leagues"."SSB"` add:

    "engine_first_season": 2043

(SSB also lacks `"ootp_version": "27"` in the local file today; optional, the guard
does not need it.)

## Verification (run on 2026-10-03 in this worktree)

- `tools/tests/test_engine_boundary.py`: 9 passed. With `--year` before the boundary: zero StatsPlus
  calls and no output folder created. Without `--year`: exactly one call (`fetch_date`), `fetch_teams`
  and the feed fetchers never ran. At the boundary season, and for a league with no boundary, the run
  continues to the first real request (the test turns it into a failure to prove it was reached).
  Every StatsPlus entry point in the tests is a function that raises if called; nothing was run against
  StatsPlus.
- `tools/tests/test_new_league.py`: 18 passed (one new case: engine_first_season checked as a whole
  year, 4 bad values rejected for both statsplus and local_export, written into the entry, the entry
  passes `settings.validate`).
- `settings.validate` rejects `"2043"`, `True`, `43`, `99999`, `2043.5`, `None`, `[2043]`, naming
  `leagues.<id>.engine_first_season`; a bad value in settings.local.json fails `settings.load` with that key
  (so doctor shows its Settings row as fail, tested).
- No default league carries the key (test): zero behavior change until the user sets one.
- `node tgs-viz/control/test/{fileMap,guards,pythonMain}.test.mjs`: 165 / 75 / 21 passed, 0 failed.
- `ingest/ratings.py --selftest`: prints `CHECK (worst 1.93e+01)` in this worktree AND in the main
  checkout with identical numbers (pre-existing, not touched).

## Decisions for the user

1. Add `"engine_first_season": 2043` under `leagues.SSB` in settings.local.json (not edited here).
   It has no effect on any run today (metadata_inputs cannot build SSB); it documents the boundary,
   and doctor --deep prints it.
2. BLM: not set. Evidence read from disk: ours has `engineFirstSeason {"27": 2058}` for both BLM-ATL and
   BLM-CIN (`leagues/*/league.json`); his BLM metadata_inputs manifest is season 2058 (in-game date
   2058-12-30), so the guard would allow today's data. That his BLM is the same league as our BLM-ATL/CIN
   is inferred from the shared name and the 2058 match, not verified. His BLM history starts 2051-01-01
   (settings.defaults.json), so seasons 2051-2057 would be refused if the guard is set to 2058.
   Recommendation: set `"BLM": {"engine_first_season": 2058}` in settings.local.json once you confirm the
   2058 boundary; it changes no number and only blocks rebuilding metadata from 2051-2057.
3. Should `other_seasons` (paste-season detection) also skip pre-boundary seasons? It only names a wrong
   paste and costs up to 4 extra StatsPlus requests; skipping saves them but loses the naming.
   Left unchanged.
