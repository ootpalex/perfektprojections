# Phase 2 row 11 - per-league validation in `doctor.py --deep` (audit, before the code)

Status: tooling. Read-only, no network, no writes. Changes no projection number.
Default `doctor.py` output stays byte-identical; the new rows exist only with `--deep`.

## What ours checks and what is ported

Ours (`model/src/validation.py`, `validate_league`): league config fields; the
regression CSVs for the OOTP version; `org.csv` columns (ID, POS, Name, ORG, OVR,
POT); `ballparks.csv` teams vs `org.csv` teams; my team is in ballparks; StatsPlus
URL reachability; metadata dir layout.

His data layout differs, so the checks are re-expressed on HIS files:

| Ours | His equivalent | Row id (`deep.<LID>.*`) |
|---|---|---|
| league config fields | per-type required fields in `leagues.<LID>` (statsplus: slug, basis; local_export: ootp_version, ootp_save, basis; dev: ootp_save + profile) and `ootp_version`/`ootp_save` pairing | `settings` |
| regression CSVs per version | `engine/calib/<basis>/constants-latest.json` (required, the New League rule) plus the optional live files (`scurves`, `hitter_tails`, `fielding_curves`, `role_stuff`, `currency`, `age_curve`, `park_blend`): each present file must parse as a JSON object. Absent optional files are legal (the engine falls back, `ratings.live_*`) and are listed, not flagged | `calib` |
| (metadata dir) | `engine/calib/<basis>/metadata-latest.json` (`cells` non-empty) and, when `metadata_inputs/` exists, its 9 CSVs' header rows against the header lists in `ingest/metadata_inputs.py` (`HIT_HDR`...) and `manifest.json` season vs `engine_first_season` | `metadata` |
| org.csv required columns | committed app files `public/data/<LID>/hitters.json` / `pitchers.json`: required keys present in EVERY record; manifest `datasets` files exist; manifest `basis` equals settings `basis` | `data` |
| ballparks vs org teams, my team in ballparks | `engine/calib/<LID>/park_factors.csv` teams vs the MLB-level (`LgLvl == "1"`) ORG names in the league's `hitters.json`, minus the NPB clubs `parks.py` excludes; `park_blend.json` home_team vs `my_team`; `my_team` in the park file | `parks` |
| StatsPlus reachable | LEFT OUT, see below | - |

## StatsPlus reachability: left out

`doctor.py` documents "No network and no writes". A probe would break that
contract for every user of `--deep`, and his `statsplus.py` rules (one request in
flight, the `/date` gate, token never printed) make even a single HEAD request a
design decision, not a tooling nicety. The existing `tokens.*` rows already say
whether a token exists. If wanted later it belongs in a separate opt-in flag
(`--online`) that calls `statsplus.fetch_date` once; not built (decision for the user).

## Input trace

| Input | Tag | Provenance |
|---|---|---|
| Required `hitters.json` / `pitchers.json` keys | 🟢 | the keys present in EVERY record of all 8 committed files (BLM, SSB, RG, TGS x hitters/pitchers; 6545/6866/5108/7532 hitters, 6515/7125/6458/6973 pitchers), chosen from the identity columns and the headline valuation column. Verified by running; list in the code constants |
| Header lists of the 9 metadata CSVs | 🟢 | imported from `ingest/metadata_inputs.py`, not copied (no drift) |
| NPB exclusion in the park comparison | 🟡 | `ingest/parks.py` `NPB` set (his, for TGS); imported |
| MLB level = `LgLvl == "1"` | 🟢 | BLM: 460 records at LgLvl 1 = 'MLB' level label; 30 distinct ORG = 30 park teams |
| Which files are optional | 🟢 | `ingest/ratings.py live_*` (each returns None when the file is missing) |
| Status policy (fail vs warn) | 🔵 | fail only where the app shows its error panel or cannot load a committed file (missing/short app data, unparsable calib JSON the engine loads unconditionally is warn: it breaks an update task, not the app). Everything else warn. Matches the doctor docstring |
| DEV league | 🔵 | trends-only: no pricing calibration, no park file; rows say so |

## Flags and resolutions

1. Park comparison on TGS: 40 park rows = 28 MLB + 12 NPB; MLB-level ORG set has
   29 entries incl. the stray value `9`. Resolved by excluding `parks.NPB` and
   ignoring digit-only ORG names (free agents / org ids).
2. RG and SSB have no park file of their own (they price in a neutral park,
   `export_league.py` `park_mode="neutral"`): row says so, no failure.
3. `hitters.json` is 35 MB (BLM): parsing it twice (existing deep check + the
   new column check) doubles the cost. Accepted for `--deep` only.
4. Disabled leagues are skipped (as doctor already does).

## Verification (run on 2026-10-03 in this worktree)

Ran:
- `tools/tests/test_doctor_deep.py`: 18 passed (fixture tree: clean, each broken case with its counts,
  sockets blocked and tree compared before/after = offline and read-only; child-process cases).
- Whole tools loop: 109 baseline tests still pass, plus the new ones (see the final report for totals).
- `doctor.py` and `doctor.py --json` before and after the change, same temp env: byte-identical
  (cmp on both outputs). test_doctor.py passes unchanged.
- `doctor.py --deep` with the main checkout's settings.local.json (BLM, RG, DEV, SSB on; read-only) and
  with TGS re-enabled in a scratch copy: every deep row is `ok` on the committed data, 0 new failures,
  about 4.7 s wall-clock for the four leagues. Row figures: BLM 6545 hitters / 6515 pitchers, SSB 6866 /
  7125, RG 5108 / 6458, TGS 7532 / 6973 records, each with all 11 / 9 required keys; BLM park file 30
  rows = 30 MLB clubs (460 BLM records at level 1, 30 distinct ORG); TGS park file 40 rows = 28 clubs +
  12 NPB excluded; BLM metadata_inputs manifest is season 2058, nine CSV headers match.
- Scratch run with `engine_first_season = 2059` on BLM: the metadata row warns (manifest season 2058 is
  before the boundary), as designed.

Inferred, not run: nothing about Windows; paths use os.path throughout.

Findings about the data (not code defects):
- `RG` (local_export) has no `my_org` in settings.defaults.json. The first draft of the check warned on
  it; RG is not a league with a club to follow, so the my_org rule is limited to `statsplus` leagues.
- `SSB` in the main settings.local.json has no `ootp_version`/`ootp_save`, which is legal (the pairing
  check warns only when exactly one of the two is set).

## Decisions for the user

1. StatsPlus reachability: left out (reason above). Option: a separate `--online` flag later, one
   `statsplus.fetch_date` request per enabled StatsPlus league. Recommendation: do not add.
2. Required-key list: the 11 hitter / 9 pitcher keys are the intersection of the committed files plus
   the headline valuation column. If the engine later renames `Max WAA wtd` / `WAA wtd` (Phase 1 WAR
   work may), update `HITTER_REQUIRED` / `PITCHER_REQUIRED` in `doctor_deep.py` in the same change.
