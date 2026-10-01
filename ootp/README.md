# ootp/ — auto-sim baseline clones and feed the regression workbook

Two tools that close the loop from "sim more baseline seasons" to "the web app shows it".

```
winsim.py        clone the pristine baseline -> drive OOTP -> auto-play 10 seasons
ingest_dumps.py  append the finished clone's dump CSVs into that league's 25 Regressions.xlsx
        |
        v   (Excel: Data -> Refresh All -> Save)
Sync Regressions.bat   regression + metadata constants -> The Sheet Hitters/Pitchers
        |
        v
Get StatsPlus Ratings.bat   engine -> tgs-viz/public/data/<league>/*.json -> web app
```

## Why clone every time

OOTP **autosaves at the end of every season and you cannot turn it off**, so simming a league
permanently mutates it. And even with aging off, players retire — a league only yields ~10
usable seasons of the *original rated cohort*. To pool many samples of "same player, same
ratings → different outcomes", you clone the pristine baseline **before every run**.

This is visible in the data: every pooled source in `25 Regressions.xlsx` shares identical
`player_id`s and all span 2016–2026. That is only possible if each run started from the same
2016 state. (BLM currently pools 7 such runs.)

**Never sim:** the pristine master, `BLM.lg`, `TheGrandestSalami.lg`. `winsim.py` refuses to,
and it also refuses to clone a *spent* league (one that already has dumps) because that
cannot reproduce the 2016 cohort.

## Setup (once per OOTP version)

Versions are **auto-discovered** — a future OOTP 28/29 needs no code change:

```bash
python ootp/winsim.py --games                 # show discovered installs + saved_games dirs
python ootp/winsim.py --game 27 --list        # which leagues are pristine / spent / real
```

Per-league config lives in `leagues.json` (game version, pristine master, clone prefix,
start/target year, which regression workbook to feed). **Moving TGS to OOTP 27 is a config
edit**: set `game` to the new version and `master` to a fresh pristine TGS-settings baseline.

### Button templates (one-time, per OOTP version)

The GUI is driven by image-matching small PNGs of OOTP's buttons. The ones in `buttons/` came
from the macOS original and **must be recaptured on Windows**. With OOTP open on its main menu:

```bash
python ootp/winsim.py --game 27 --list-windows   # confirm the window title
python ootp/winsim.py --game 27 --grab           # writes ootp/winsim_grab.png
#   crop each button TIGHTLY out of that -> ootp/buttons/<same-name>.png
python ootp/winsim.py --game 27 --calibrate      # moves the mouse to each match
```
Buttons for screens not currently showing read `NOT FOUND` — expected. Calibrate each on the
screen where it appears.

Also make sure **"Export CSV files after each simulated season"** stays ON in the baseline's
league setup — the per-year dump is how `winsim` knows a sim finished.

## Run it

```bash
python ootp/winsim.py --league BLM --runs 3 --dry-run   # plan only
python ootp/winsim.py --league BLM --runs 3             # clone 6.lg -> blm-run01..03, sim each
```
Abort any time: slam the mouse into a screen corner (pyautogui FAILSAFE) or Ctrl-C.
Ctrl-C stops winsim but **not** OOTP's in-flight sim.

## Continuous mode (the DEV TESTS league)

One long-lived OOTP 27 league, every team AI-controlled, simmed in place year after year. No
clone, no pristine check, no year_NNNN.png: the tool reads the year list in the AUTO-PLAY dialog
off the screen (digit glyphs are cut from that list on the first run into `buttons/digits/`) and
refuses to auto-play when the league on screen sits in the wrong year. Profile `DEV` in
`leagues.json` names the saved game (`folder`). Dumps are never deleted or moved.

```bash
python ootp/winsim.py --league DEV --sim --dry-run          # the plan, nothing clicked
python ootp/winsim.py --league DEV --test-load "DEV TESTS"  # first time: does the row click load it?
python ootp/winsim.py --league DEV --test-year              # first time: date picker, no AUTO-PLAY
python ootp/winsim.py --league DEV --sim --years 5          # sim 5 seasons from the last dump + 1
```
`Sim Dev League.bat` (repo root) runs the sim, then banks the dumps and rebuilds the DEV trends.

## Ingest

```bash
python ootp/ingest_dumps.py --league BLM --list        # clone status: pending / INGESTED
python ootp/ingest_dumps.py --league BLM --all-new     # dry-run: shows rows to add
python ootp/ingest_dumps.py --league BLM --all-new --write
```

**Two safety checks (won't double-add, won't add the wrong league):**
- **No double-add:** every import is recorded in `ingested.json`; `--all-new` skips recorded
  clones and an explicit re-add aborts. If a workbook ALREADY holds clone data from before this
  tool (e.g. BLM's `1..5,baseline02` still on disk), run `ingest_dumps.py --league X --mark-done`
  ONCE to record them as already-in-the-sheet so they're never re-added.
- **Baseline-only:** candidates exclude real/protected leagues and the pristine master; then each
  clone's player_ids are checked against the sheet's Hitters/Pitchers ratings, and any under 90%
  match is skipped ("not a clone of this baseline"). A stray league can't ride in.

- **Append-only, never rebuild.** The workbook pools clone runs, and some of those leagues no
  longer exist on disk — a rebuild would silently destroy sample.
- The dump CSV is a **career** file (all seasons 2016..last), so one clone = one complete
  sample, ingested exactly once. `ingested.json` records which clones were added so you
  cannot double-add.
- Writes raw XML: extends each Excel Table's `ref` + `autoFilter` and the sheet `dimension`,
  leaving the PivotTables, charts and Power Pivot Data Model untouched. (openpyxl would
  destroy them — verified.) A timestamped `.bak-` copy is made first.
- `Fielding`'s `pa`/`pm` are calculated table columns; the ingester emits their formulas.
- Ratings (`Hitters`/`Pitchers` tables) are **not** touched — clones share the baseline roster,
  so their ratings already cover these `player_id`s. If you ever build a new pristine
  baseline, refresh those tables too.

**After ingesting:** open the workbook in Excel → **Data → Refresh All** (rebuilds the Data
Model + regression pivots) → **Save**. Then run `Sync Regressions.bat`.

## Attribution

GUI automation (macro engine, edge-based template matching, dump-watching) is adapted from
[ootpalex/ootp-autosim](https://github.com/ootpalex/ootp-autosim) (MIT, macOS). The Windows
platform layer, the clone orchestration and the guardrails are new; this is a **local copy**,
not a dependency on that repo.
