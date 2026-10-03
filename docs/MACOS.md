# Running the app on macOS

The app, the StatsPlus pulls, the engine and ML scoring run on macOS (Apple Silicon) and
Linux. OOTP automation (winsim) stays Windows-only. Every change behind this is either
gated on `os.name` / `sys.platform` or lives in a new file, so Windows behaves as before.

## Setup

1. Homebrew's OpenMP runtime. xgboost's macOS wheel links `libomp.dylib`; without it
   `import xgboost` fails and ML scoring stops.

   ```bash
   brew install libomp
   ```

2. One virtual environment for both the main and the ML interpreter (Python 3.13):

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt -r requirements-ml.txt -r requirements-dev.txt
   ```

3. The app's packages (Node 22):

   ```bash
   cd tgs-viz && npm install
   ```

4. `settings.local.json` at the repo root (gitignored). Point both interpreters at the venv
   and turn off the leagues you do not play in:

   ```json
   {
     "python": { "main": ["/abs/path/to/repo/.venv/bin/python"], "ml": ["/abs/path/to/repo/.venv/bin/python"] },
     "leagues": { "TGS": { "enabled": false } }
   }
   ```

   Without it, the committed Windows defaults are swapped for `python3` (see below).

5. Restore the ratings archive (every update task refuses until it exists):

   ```bash
   .venv/bin/python tgs-viz/backtest/vintage_backup.py --restore
   ```

6. Add a league with the New League wizard on the Control page (or `tgs-viz/tools/new_league.py`),
   and paste its StatsPlus token after `<ID>=` in `StatsPlus Tokens.txt` (gitignored).

7. Double-click a launcher in Finder:

   | Launcher | Runs |
   |---|---|
   | `Launch Dashboard.command` | the app on port 3000 (twin of `Launch TGS.bat`) |
   | `Check Setup.command` | `run_task.py doctor` |
   | `Get StatsPlus Ratings.command` | `run_task.py update.<DASH_LEAGUE>` (default `SSB`); the bat's `get_ratings` needs TGS and BLM both on |

   `DASH_PY` overrides the interpreter; by default the launchers use `.venv/bin/python`,
   else `python3`.

## What is platform-branched, and where

| Where | Off Windows |
|---|---|
| `tgs-viz/tools/settings.py` `_platform_defaults`, `tgs-viz/control/paths.js` `platformDefault` | A committed default still equal to its Windows text is swapped: `python` / `py -3.14` → `python3`; a `C:/` or `%USERPROFILE%` saved_games → `~/Library/Application Support/Out of the Park Developments/OOTP Baseball <v>/saved_games`. `settings.defaults.json` is unchanged; the local file is never swapped. |
| `tgs-viz/tools/run_task.py` `native()` | Step path templates in `tasks.py` are written with `\`; they get `/` before placeholders are filled. Also `exists` (and `conditions.py`). |
| `run_task.py` `press_enter()` | Console gates use `ask()` instead of cmd's `pause`. |
| `run_task.py` spawns | Job-mode steps and the detached runner start in their own session (`start_new_session`). |
| `run_task.py` `kill_tree`, `cmd_kill` → `joblock.posix_kill_tree` | The twin of `taskkill /T /F`: descendants (ps) and the process groups they lead, SIGTERM then SIGKILL. |
| `tgs-viz/tools/joblock.py` `proc_start_time` | macOS: libproc `proc_pidinfo(PROC_PIDTBSDINFO)`; Linux: `/proc/<pid>/stat`. A zombie reads as gone on both, as on Windows. |
| `joblock.py` `take_lock` | `os.link` (atomic, fails when the lock exists); POSIX `rename` would overwrite. |
| `tgs-viz/tools/doctor.py` | Checks `node_modules/.bin/vite`, no `win32gui`, no `py -3` probe; the pip fix text names the configured interpreter. |
| `ootp/winsim.py` | The import-time `ctypes.windll` is guarded, so `--list`, `--dry-run` and `cleanup_clones.py` import. |
| `tgs-viz/backtest/dump_source.py`, `tgs-viz/ingest/export_league.py` | The macOS saved_games folder is in the discovery fallbacks. |
| `requirements.txt` | `pywin32` only on `win32`. |
| `tgs-viz/control/test/mock_tools/run_task.py` | Uses joblock's POSIX helpers, so the Control smoke tests run. |

## Still Windows-only

- **OOTP automation**: `ootp/winsim.py` and the tasks that drive OOTP (Grind, Sim Dev League,
  the `ootp/*.bat` tools, Recalibrate's sim steps). They import, but they do nothing useful off
  Windows.
- **`test_bat_equivalence.py`**: it proves the `.bat` wrappers against the old bats; off Windows
  it prints a skip line and exits 0.
- **The `.bat` launchers** themselves (left as they are, `*.bat eol=crlf`).
- Tasks that read an OOTP save's exports (draft board, Rule 5, IAFA, Update Regular Game) need
  OOTP and its save on this Mac.

## Tests

Run each module in its own process: the modules set their environment at import and cache
settings-dependent modules, as under `unittest discover`.

```bash
for f in tgs-viz/tools/tests/test_*.py; do .venv/bin/python -m pytest "$f" -q; done
```

```bash
for f in tgs-viz/control/test/{fileMap,guards,pythonMain}.test.mjs tgs-viz/tests/client/*.test.mjs; do node "$f"; done
```

CI (`.github/workflows/ci.yml`) runs these, the Control smoke tests and `npm run build` on
macOS and Ubuntu.
