# Control panel: build spec

Status: build spec, revision 2, 2026-10-01. Base commit: `ef23800` (branch `control-panel`). Revision 2 folds in two reviews (user setup, works and safe). Section 19 lists the decisions left to the user; section 20 lists the objections not taken and why.
Worktree: `C:\Users\perfe\Desktop\TGS-control-wt`. All paths below are relative to the worktree root unless they start with a drive letter.

Changed decision (concrete reason, from both reviews): decision 3 said "one job at a time". A Grind runs for days (Grind TGS.bat:26, :66), and today the user can run Get StatsPlus Ratings in its own window during a Grind. One global lock would refuse that pull for days. Revision 2 replaces the single lock with named locks (section 7.5): two jobs that drive OOTP or touch the same clone saves never run together, and jobs that write app data take turns on one `data` lock, which a Grind holds only during its recalibrate steps.

Four implementers build this in parallel without talking to each other:

- **A**: Python task registry, runner, bat wrappers, equivalence test.
- **B**: Vite control plugin and the server side of live refresh.
- **C**: React: Control page, New League wizard UI, Setup page, live-refresh client, ErrorScreen fix, nav.
- **D**: settings module, refactor of the must-configure hard-coded values, New League backend, `doctor.py`, requirements files.

Every shared contract is fixed in this file. If a contract here is wrong or impossible, do not invent a new one: build to the contract, write the problem in your final report, and let the integrator decide.

The user's goal, in their words (2026-10-01): "an app that opened and i could click what i wanted to do and it would run what i needed and prompt me if i need to input something." Hard requirement: "make sure my leagues still load up on my version so i dont have to do any extra stuff" (TGS and BLM online StatsPlus leagues, RG local save, DEV research league).

---

## 1. Ground rules (all implementers)

1. Never edit anything in `C:\Users\perfe\Desktop\TGS Projections` (the user's live checkout). You may read its gitignored data (ingest/.cache, ratings_history.db, calib CSVs) to learn a format. Never open, print or copy `StatsPlus Tokens.txt`.
2. Edit only the files you own (section 2). Read anything.
3. No new npm packages. `tgs-viz/package.json` dependencies and `package-lock.json` stay byte-identical. Launch TGS.bat never runs `npm install`. Vite bundles chokidar, ws, sirv and connect internally; none of them is importable from tgs-viz. Use Node built-ins and Vite's own server objects only. Do not import picomatch or tinyglobby (transitive deps).
4. Python tools you write use the standard library only and run on Python 3.11 or newer (the user runs 3.13 as `python` and 3.14 as `py -3.14`). 3.11 is the one supported minimum everywhere (doctor, README, requirements): `numpy>=2.4.2` needs it.
5. Never start a dev server on port 3000 (the user's app). Test ports: B uses 3101, C uses 3102, integration uses 3100. Always pass `--strictPort`. Every test server also sets `TGS_VITE_CACHE_DIR` to its own folder (`<worktree>\.vite-cache-b`, `-c`, `-int`). The worktree's `tgs-viz/node_modules` is a junction to the user's `node_modules`, and Vite's default cache is `node_modules/.vite` (config.js:35530). A test server with its own root gets a new config hash and would re-optimize into the folder the user's running app serves from. (Vite also writes its short-lived bundled config to `node_modules/.vite-temp/` under a unique name and deletes it after loading; that does not touch the user's cache.)
6. Never run a real pipeline job that touches the network, StatsPlus, OOTP, the mouse, or the user's saves. Use the selftest tasks (section 4.9). Exceptions are listed in the test plans (section 15).
7. Test isolation: point every test server and test run at its own control folder with `TGS_CONTROL_DIR` (section 3.1). B: `.control-b`, C: `.control-c`, A's unit tests: a temp dir.
8. Do not commit. The integrator commits after integration.
9. Never edit `tgs-viz/vite.config.js` while a job started from that dev server is running: Vite restarts on that edit (expected), but it is the one case the restart path must cover, so test it on purpose, not by accident. Files under `tgs-viz/control/` are loaded with a dynamic import that Vite does not bundle (8.1), so they are not config dependencies: an edit to them takes effect at the next Vite start and restarts nothing.
10. tgs-viz is an ESM package (`"type": "module"`). Plugin files are `.js` ESM. Any CommonJS file must be `.cjs`.
11. Every `.bat` you write is CRLF, ASCII only.
12. Prose rules for user-facing text (page copy, console messages, errors): plain words, short sentences, active voice, no em dashes. Never tell the user to run `python extract_data.py` (it overwrites engine data with stale Excel values, see extract_data.py:604-611 and STATUS.md:180).
13. Never call `os.kill(pid, 0)` in Python on Windows: `signal.CTRL_C_EVENT == 0`, so it sends Ctrl+C to that process group instead of testing it. Process checks go through `joblock.proc_start_time()` (7.6). In Node, `process.kill(pid, 0)` is a safe yes/no liveness query (libuv answers signal 0 with `GetExitCodeProcess`), but it cannot tell a reused pid apart, so B uses it only as a cheap first check (8.8).
14. Every Vite plugin entry point (`configureServer`, `hotUpdate`, watcher and ws handlers, middleware, timers, child process events) catches its own errors. Nothing the control code does may stop Vite or the `/data` files from serving (8.10).

---

## 2. File list and owners

No file has two owners. "New" means it does not exist at `ef23800`.

### A: registry, runner, wrappers

| File | New/Mod | Purpose |
|---|---|---|
| `tgs-viz/tools/tasks.py` | New | Task registry (section 4, 5) |
| `tgs-viz/tools/run_task.py` | New | Runner: console mode, job mode, `--plan`, `--list-json` (section 6) |
| `tgs-viz/tools/joblock.py` | New | Named locks, active-job registry, job folder, atomic JSON write, process identity (section 7) |
| `tgs-viz/tools/conditions.py` | New | Condition evaluator for `when` / `ask_when` (section 4.4) |
| `tgs-viz/tools/selftest_steps.py` | New | Harmless step actions for selftest tasks (section 4.9) |
| `tgs-viz/tools/tests/batsim.py` | New | Interpreter for the old bat subset (section 14.1) |
| `tgs-viz/tools/tests/test_bat_equivalence.py` | New | Equivalence test |
| `tgs-viz/tools/tests/test_run_task.py` | New | Runner unit tests |
| `tgs-viz/tools/tests/test_catalog.py` | New | Catalog shape test |
| `tgs-viz/tools/tests/fixtures/conditions_cases.json` | New | Shared condition cases (4.4). C's `inputConditions.test.mjs` reads this file too |
| `tgs-viz/tools/tests/legacy_bats/*.bat.legacy` | New | Byte copies of the 18 bats at `ef23800` (`git show ef23800:<path>`); ootp ones under `legacy_bats/ootp/` |
| `Get StatsPlus Ratings.bat`, `Get StatsPlus History.bat`, `Bank Season.bat`, `Bank Dev Seasons.bat`, `Grind TGS.bat`, `Grind BLM.bat`, `Recalibrate TGS.bat`, `Recalibrate BLM.bat`, `Sim Dev League.bat`, `Sync Metadata.bat`, `Update Dispersal Board.bat`, `Update Draft Board.bat`, `Update Regular Game.bat` | Mod | Thin wrappers (section 6.5) |
| `ootp/1 - Check OOTP (26).bat`, `ootp/2 - Grab a menu (26).bat`, `ootp/3 - Sim TGS (preview).bat`, `ootp/4 - Sim TGS.bat`, `ootp/TEST year picker.bat` | Mod | Thin wrappers |
| `old bats (backup)/*.bat`, `old bats (backup)/ootp/*.bat` | New | Runnable copies of the 18 legacy bats for one release, a fallback if run_task breaks (6.7) |
| `Launch TGS.bat` | Mod | Node check, node_modules check, `--strictPort`, pause on error (section 6.6) |
| `Check Setup.bat` | New | Wrapper for task `doctor` (for users who cannot start the app yet) |
| `.gitattributes` | New | Two lines: `*.bat text eol=crlf` and `*.bat.legacy -text` |

### B: Vite plugin, live refresh server side

| File | New/Mod | Purpose |
|---|---|---|
| `tgs-viz/control/plugin.js` | New | Plugin factory `tgsControl()`: `configureServer`, ws handlers, dispose on close |
| `tgs-viz/control/http.js` | New | `/__tgs/` router, JSON helpers, request validation (8.5) |
| `tgs-viz/control/guards.js` | New | Loopback, Host, Origin, token, content-type checks (pure functions) |
| `tgs-viz/control/jobs.js` | New | Spawn, active-job and state reading, SSE tailing, stop/answer writes, catalog cache, `--reap` and `--kill` calls |
| `tgs-viz/control/watch.js` | New | public/data watcher, debounce, hold and flush rules (9.3), `tgs:data` broadcast |
| `tgs-viz/control/fileMap.js` | New | Pure map: data file path to `{league, key}` (section 9.2) |
| `tgs-viz/control/paths.js` | New | Repo root, control dir, settings read for `python.main` |
| `tgs-viz/control/safe.js` | New | `safe(where, fn)` wrapper and the rate-limited one-line error log (8.10) |
| `tgs-viz/control/test/fileMap.test.mjs`, `guards.test.mjs`, `api.smoke.mjs`, `restart.smoke.mjs`, `failsafe.smoke.mjs`, `pythonMain.test.mjs` | New | Tests (section 15.2) |
| `tgs-viz/control/test/fixtures/python_main_cases.json` | New | Shared cases for the `python.main` merge (3.2). D's `test_settings_defaults.py` reads this file too |
| `tgs-viz/vite.config.js` | Mod | Guarded plugin loader, inline public/data `hotUpdate`, `cacheDir`, `server.watch.ignored` (8.1) |
| `tgs-viz/src/index.css` | Mod | Line 1 only, replaced by three lines (section 9.1) |
| `tgs-viz/package.json` | Mod | Remove the `"extract"` script (line 10) and nothing else |

### C: React

| File | New/Mod | Purpose |
|---|---|---|
| `tgs-viz/src/lib/controlApi.js` | New | Token handshake, fetch wrapper, SSE helper, catalog/config cache, active-jobs store |
| `tgs-viz/src/lib/dataVersion.js` | New | Live-refresh version store, `useDataVersion`, changed-file sets, cache invalidation |
| `tgs-viz/src/lib/softMerge.js` | New | Pure soft-refresh rules: which keys to refetch, keep-old merge (node-testable) |
| `tgs-viz/src/lib/inputConditions.js` | New | Pure evaluator for `ask_when` (mirror of section 4.4) |
| `tgs-viz/src/hooks/useSelectedById.js` | New | Selected player kept by ID and re-resolved from the current rows (9.4) |
| `tgs-viz/src/pages/ControlPage.jsx` | New | Control page with nested routes |
| `tgs-viz/src/components/control/TaskCard.jsx`, `TaskForm.jsx`, `JobPanel.jsx`, `JobLog.jsx`, `PromptCard.jsx`, `NewLeagueWizard.jsx`, `SetupPanel.jsx` | New | Control UI parts |
| `tgs-viz/tests/client/softMerge.test.mjs`, `inputConditions.test.mjs` | New | Node tests |
| `tgs-viz/src/App.jsx` | Mod | Shell, nav, routes, ErrorScreen, footer status |
| `tgs-viz/src/hooks/usePlayerData.js` | Mod | Soft refresh from raw lists, changed files only |
| `tgs-viz/src/lib/ratingTrends.js`, `src/lib/ageCurve.js` | Mod | Cache invalidation exports |
| `tgs-viz/src/pages/MakeItOddsPage.jsx`, `CalibrationPage.jsx`, `TrendsPage.jsx`, `HittersPage.jsx`, `PitchersPage.jsx`, `DraftBoardPage.jsx`, `MockDraftPage.jsx`, `RosterOptimizerPage.jsx`, `MarketValuePage.jsx`, `OrganizationPage.jsx`, `WaiverClaimPage.jsx` | Mod | Version deps, selection by ID, default org |
| `tgs-viz/src/components/PlayerDetail.jsx` | Mod | Version deps |

### D: settings, refactor, New League backend, doctor

| File | New/Mod | Purpose |
|---|---|---|
| `tgs-viz/tools/settings.py` | New | Settings API (section 3.2) |
| `tgs-viz/tools/settings.defaults.json` | New | Committed defaults = today's values (section 3.2) |
| `tgs-viz/tools/new_league.py` | New | New League backend (section 12) |
| `tgs-viz/tools/doctor.py` | New | First-run check (section 13) |
| `tgs-viz/tools/tests/test_settings_defaults.py`, `test_new_league.py`, `test_doctor.py` | New | Tests |
| `requirements.txt`, `requirements-ml.txt` (repo root) | New | Section 13.3 |
| `.gitignore` | Mod | Section 13.4 |
| Pipeline files in section 11 | Mod | Refactor, new CLI flags, EOF guards, write retries, archive guard, atomic `refresh.py` writes |

---

## 3. Shared contracts

### 3.1 Paths and environment variables

- Repo root = the folder holding `Launch TGS.bat`. Python: `Path(__file__).resolve().parents[2]` from `tgs-viz/tools/*.py`. Node: `path.resolve(viteRoot, '..')`.
- Control folder = `<repo>/.control/` unless `TGS_CONTROL_DIR` is set (absolute path). It is outside the Vite root (`tgs-viz/`), so Vite never watches it. Gitignored by `/.control*/`.
- Settings: defaults `tgs-viz/tools/settings.defaults.json`; local override `<repo>/settings.local.json` unless `TGS_SETTINGS_LOCAL` is set (tests only).

| Variable | Set by | Read by | Meaning |
|---|---|---|---|
| `TGS_CONTROL_DIR` | tests, dev server env | A, B | Control folder override |
| `TGS_SETTINGS_LOCAL` | tests | D (and B for `python.main`) | Local settings path override |
| `TGS_SELFTEST=1` | test dev servers | A, B | Show and allow `selftest.*` tasks |
| `TGS_DRY_RUN=1` | wrapper smoke tests | A | Console mode prints the plan, runs nothing, takes no lock |
| `TGS_SECRET_<NAME>` | B at spawn | A (`run_task.py --job`) | One secret input. B upper-cases the name, because Python's `os.environ` upper-cases every key on Windows. run_task matches it to the task's declared secret inputs without regard to case, moves the value into memory and deletes it from `os.environ` before any step |
| `TGS_NL_TOKEN` | A, for one step only | D (`new_league.py token`) | StatsPlus token typed in the wizard or the Replace token form |
| `TGS_JOB_ID` | A, every step | D (`doctor.py`), selftests | The running job's id, so doctor can recognize its own job |
| `TGS_VITE_CACHE_DIR` | test dev servers | B (`vite.config.js`) | Vite `cacheDir` override (rule 1.5). Unset on the user's PC, so the default stays |
| `RATINGS_DB_ALLOW_NEW=1` | worktree tests only | D (`ratings_db.connect`), A (archive check, 7.3) | Lets a missing ratings archive be created next to existing vintages (11.22) |
| `TGS_CONTROL_TEST_THROW` | B's failsafe test only | B | `import`: plugin.js throws while it loads; `configure`: it throws inside `configureServer` (15.2 step 9) |
| `TGS_RUN_TASK_TEST_CRASH=1` | A's tests only | A | run_task raises right after it writes state `starting` (15.1) |
| `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8` | B at spawn; A for job-mode steps | Python | Unbuffered UTF-8 output into pipes |
| `STATSPLUS_COOKIE` | A, per step, from secret inputs | refresh.py:269, statsplus_history.py:911 | Browser cookie pair, never written to disk |

### 3.2 Settings (D implements, everyone reads)

#### settings.defaults.json (exact content, values = today's behavior)

```json
{
  "schema": 1,
  "python": { "main": ["python"], "ml": ["py", "-3.14"] },
  "node": ["node"],
  "statsplus": { "token_file": "StatsPlus Tokens.txt" },
  "ootp": {
    "installs": {
      "26": { "saved_games": "C:/OOTP 26/data/saved_games" },
      "27": { "saved_games": "%USERPROFILE%/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games" }
    },
    "protected_extra": ["new game"]
  },
  "app": { "port": 3000 },
  "leagues": {
    "TGS": {
      "type": "statsplus", "name": "TGS", "slug": "tgs", "basis": "TGS",
      "ootp_version": "26", "ootp_save": "TheGrandestSalami",
      "my_team": "Chicago Cubs", "my_org": "Chicago Cubs",
      "history": { "first_date": "2038-01-01", "probe_years": 0 },
      "dispersal_orgs": ["Atlanta Hammers", "Detroit Tigers", "San Francisco Giants", "Seattle Mariners"]
    },
    "BLM": {
      "type": "statsplus", "name": "BLM", "slug": "blm", "basis": "BLM",
      "ootp_version": "27", "ootp_save": "BLM",
      "my_team": "Tampa Bay Rays", "my_org": "Chicago (N) Cubs",
      "history": { "first_date": "2051-01-01", "probe_years": 0 }
    },
    "RG": {
      "type": "local_export", "name": "Regular Game", "basis": "BLM",
      "ootp_version": "27", "ootp_save": "Regular Game"
    },
    "DEV": {
      "type": "dev", "name": "Dev test (all-AI sim)",
      "ootp_version": "27", "ootp_save": "DEV TESTS"
    }
  }
}
```

Where each value comes from today: OOTP 26 path (Grind TGS.bat:38, draft.py:91, r5.py:29, iafa.py:32), OOTP 27 path (Grind BLM.bat:38, draft.py:86, r5.py:30, iafa.py:33), saves (draft.py:91-97, r5.py:35-36, iafa.py:37-40, Update Regular Game.bat:23, ootp/leagues.json:22-23), `my_team` (parks.py:48, :50), `my_org` (what `/cub/i` picks today at OrganizationPage.jsx:301 and WaiverClaimPage.jsx:55; BLM checked by the critic), slugs (statsplus_token.py:32), history dates (statsplus_history.py:221, :227), dispersal orgs (Update Dispersal Board.bat:19), interpreters (Get StatsPlus Ratings.bat:25 and :118), port (Launch TGS.bat:11), protected `new game` (winsim.py:81).

`my_team` = the park home club (parks.py). `my_org` = the org the Org Builder and Waivers pages open on. They differ for BLM on purpose (critic item 17).

#### Field rules

- League id: `^[A-Z0-9]{2,8}$`, and not a Windows device name (`CON`, `PRN`, `AUX`, `NUL`, `COM0` to `COM9`, `LPT0` to `LPT9`). Types: `statsplus`, `local_export`, `dev`, `clone`.
- `enabled` (bool, default true). A local entry `{"enabled": false}` hides a default league: its tasks leave the catalog and its data stays on disk.
- `pending` (bool, local file only): set by New League while a league is being added (12.3), removed by `register`. A pending league has no tasks in the catalog, but `league(id)`, `slug(id)` and `ootp_save_dir(id)` already answer for it, so the first pull runs with its settings. The list functions (`leagues()`, `slug_map()`, `online_leagues()`, `history_settings()`, `extra_leagues()`, `app_config()`) leave pending leagues out; `protected_saves()` and `league_saves()` include them.
- `slug`: `^[a-z0-9_-]{1,40}$`. Default `id.lower()`.
- `basis`: `TGS` or `BLM` (the calibration a league prices with). For TGS and BLM it equals the id.
- `ootp_profile` (optional, object): a winsim profile for a `dev` or `clone` league added by New League (same keys as `ootp/leagues.json` entries). TGS, BLM and DEV keep their profiles in `ootp/leagues.json`.
- `foreign_league_ids` (optional, list of strings): StatsPlus League ids to drop for a new online league. Default empty.
- Interpreter values are argv arrays, never strings. Nothing in an interpreter argv is expanded (no `%VAR%`, no `~`): the array is passed to the OS as written.
- Paths: `%VAR%` and `~` are expanded. Nothing else.

#### Merge rule

Deep merge of dicts, local wins. Lists are replaced, not merged. `leagues` merges per id (deep merge inside each league). A local league id not in defaults is a new league. Invalid JSON or a failed validation in either file raises `SettingsError` with a plain message naming the file and the key. Pipeline scripts and run_task stop on it; they never fall back silently. The two exceptions report instead of stopping: `run_task.py --list-json` returns a catalog that holds only `doctor`, with `state.settings_error` set (3.4), and `doctor.py` reports it as the `settings` check.

#### settings.py API (stable names; A, B and D code against these)

```python
REPO: str
DEFAULTS_PATH: str
LOCAL_PATH: str                       # honors TGS_SETTINGS_LOCAL
class SettingsError(Exception): ...

def load(refresh: bool = False) -> dict          # merged; cached by both files' (mtime_ns, size)
def interp(key: str) -> list[str]                # "main" | "ml" | "node"
def leagues(include_disabled: bool = False) -> dict[str, dict]   # id -> merged league dict, each has "id";
                                                 # include_disabled=True also returns disabled and pending leagues
def league(league_id: str) -> dict | None        # any configured league, enabled, disabled or pending
def slug(league_id: str) -> str                  # settings slug, else id.lower()
def slug_map() -> dict[str, str]                 # {id: slug} for enabled, non-pending statsplus leagues, defaults order first
def online_leagues() -> list[str]
def saved_games_raw(version: str) -> str | None  # env-expanded, NOT normalized (used for bat-identical argv)
def saved_games(version: str) -> str | None      # os.path.normpath of the raw value
def ootp_save_dir(league_id: str) -> str | None  # saved_games(ootp_version)/<ootp_save>.lg
def protected_saves() -> set[str]                # lowercased; uses leagues(include_disabled=True); see 11.14
def league_saves() -> set[str]                   # lowercased ootp_save of EVERY configured league, any type,
                                                 # enabled or not (cleanup_clones never deletes these, 11.15)
def ootp_profiles() -> dict                      # ootp/leagues.json merged with leagues.<id>.ootp_profile
def history_settings() -> dict[str, dict]        # {id: {"first_date", "probe_years"}} for leagues with history
def token_file() -> str                          # absolute; STATSPLUS_TOKEN_FILE env still wins (statsplus_token.py:57)
def app_config() -> dict                         # browser-safe subset, section 3.4
def extra_leagues() -> dict[str, str]            # {id: basis} for enabled statsplus/local_export leagues whose basis != id
def validate(merged: dict) -> list[str]          # problems, plain words
def write_local(patch: dict) -> dict             # deep-merge patch into the local file, validate, atomic write; returns merged

# CLI
# python tgs-viz/tools/settings.py --json            merged settings
# python tgs-viz/tools/settings.py --app-json        app_config()
# python tgs-viz/tools/settings.py get <dotted.key>
# python tgs-viz/tools/settings.py set --patch-file <path>   prints {"ok": true, "merged": {...}} or {"ok": false, "errors": [...]}, exit 0/2
# python tgs-viz/tools/settings.py validate          exit 0 ok, 2 problems
```

Atomic write: write `<file>.<pid>.tmp`, then `os.replace` with up to 10 tries 200 ms apart on `PermissionError`.

Import pattern for pipeline scripts: `sys.path.insert(0, os.path.join(REPO, "tgs-viz", "tools")); import settings as ST`. Import inside functions where a module is imported by the ML interpreter too; it must work under both interpreters.

Node reads only `python.main`: local file value if the local file parses and that value is a non-empty array of strings, else the defaults value, else `["python"]`. No expansion. Everything else comes from Python through the catalog. Both sides test this rule against one shared case file, `tgs-viz/control/test/fixtures/python_main_cases.json` (B owns it): a list of `{"name", "defaults": <object or null>, "local": <file text or null>, "expect": [...]}`. Cases: no local file; local without `python`; local `python.main` valid; local `python.main` an empty list; local `python.main` a string; local file not valid JSON (Node falls back to defaults; Python raises SettingsError, which the case records as `"expect_python": "SettingsError"`); a value holding `%USERPROFILE%` (kept as written).

### 3.3 Task registry schema (A)

`tasks.py` exposes `build_registry(settings_module, state) -> list[Task]` (plain dicts, JSON-serializable).

```python
Task = {
  "id": "get_ratings",                 # [A-Za-z0-9_.-]+ ; generated ids use "<kind>.<LEAGUE>"
  "title": "Get StatsPlus Ratings",
  "description": "Pulls current ratings for TGS and BLM ...",   # plain words, 1-3 sentences
  "group": "everyday",                 # see 4.1
  "leagues": ["TGS", "BLM"],
  "bat": "Get StatsPlus Ratings.bat",  # or None
  "requires_leagues": ["TGS", "BLM"],  # left out when any is missing, disabled or pending
  "flags": {
    "writes_app_data": True, "heavy": False, "long": False, "endless": False,
    "drives_ootp": False, "needs_ootp_closed": False, "needs_excel_closed": False,
    "network": True, "secret_inputs": True, "hidden": False,
    "read_only": False,                # takes no lock at all (7.5); still gets a job folder
    "needs_archive": True              # refuses at start when the ratings archive is missing (7.3)
  },
  "locks": ["task.get_ratings"],       # whole-run locks (7.5); "data" is never listed here, steps take it
  "time": "5 to 15 minutes",
  "inputs": [Input, ...],
  "banner": ["", " ===============================================", ...],   # console text, the bat's echo text
                                                                    # after cmd's caret rules (14.1)
  "steps": [Step, ...],
  "loop": None | {"from_step": "winsim", "cycle_echo": [...]},       # endless tasks
  "finish": Finish,
  "stop_modes": ["after_step", "kill"],   # endless tasks: ["after_cycle", "after_step", "kill"]
  "rollback": None | {"run": [...argv...], "until_step": "register"},
                                       # New League only (12.3): run when the job ends failed, stopped
                                       # or killed before until_step finished ok
}

Input = {
  "name": "sessionid",
  "type": "choice" | "text" | "secret" | "confirm",
  "label": "Browser cookie: sessionid",
  "help": "...",
  "required": False,
  "default": None,
  "choices": [{"value": "TGS", "label": "TGS"}],     # choice only
  "format": None | "int",  "min": 1, "max": 50,      # text only ("statsplus_token" on a secret: the browser checks the token shape, 10.4)
  "ask_when": Condition | None,                       # None = always
  "console": None | {                                 # None = console mode uses the default, asks nothing
      "prompt": "Paste your sessionid value, then press Enter:",
      "loop_until_valid": False, "invalid_echo": [" Please type TGS or BLM."]
  },
  "equals": None | "XY",                             # text only: the value must equal this (remove_league's confirm_id)
  "from_argv": None | 1,                              # console positional argument index (Sim Dev League %1)
  "modes": ["console", "job"]                         # ["job"] for the ootp_ready style confirms: console mode
                                                      # uses the bat's gate pause instead and never asks them
}
# secret inputs (job mode): blank is allowed unless required; a non-blank value must have 8 to 4096
# characters after trimming and no CR, LF or NUL. B (8.5), run_task and the browser (10.3) all check this.

Step = {
  "id": "tgs_ratings",
  "title": "TGS ratings",
  "kind": "run" | "probe" | "gate" | "exists_check" | "prelude" | "excel_check",
  "echo": [" --- TGS (OSA ratings) ---"],             # console and job log, printed before the step
  "run": ["@py", "tgs-viz\\ingest\\refresh.py", "--statsplus", "--league", "TGS", "--write"],
  "when": Condition | None,
  "on_error": "collect" | "fail" | "ignore" | "stopafter" | {"handler": "history_codes"},
  "tag": "TGS-ratings",                               # FAILS tag for collect
  "fail_echo": [],                                    # printed after a nonzero exit (Bank Season.bat:38, :43)
  "writes_app_data": True,
  "app_leagues": ["TGS"],                             # fileMap leagues of the public/data files the step writes;
                                                      # "*" = files that map to league null (9.2). Table in 9.3
  "data": True,                                       # needs the data lock (7.5). Defaults below the schema
  "drives_ootp": False,                               # job mode: the 5 s "Hands off" countdown before the first
                                                      # such step (7.3); after a kill, run_task resets input
  "env": {"STATSPLUS_COOKIE": "@cookie"},             # "@cookie" = the prelude's cookie value or unset
  "set_flag": None | "tok_TGS",                       # probe: flag = (exit == 0); a probe never fails the job
                                                      # (status ok, exit code recorded)
  "job": None | Interactive,                          # job-mode substitute, see 6.3
  "excel": None | {"folder": "The Sheets TGS",        # excel_check only (7.3); job mode only, console skips it
                   "files": ["The Sheet Hitters.xlsx", "The Sheet Pitchers.xlsx"]},
}

Interactive = {
  "kind": "preview_confirm",
  "preview": [...argv...], "apply": [...argv...],
  "count_regex": "^\\s+(\\d+) cell\\(s\\) will change",  # sum of group(1) over matching lines; 0 or no match = skip
  "question": "Apply these changes to The Sheets TGS?",
  "yes_label": "Apply", "no_label": "Skip"
}

Finish = {
  "style": "fails" | "failfast",
  "ok_echo": [...], "fails_echo": [...], "fail_echo": [...], "stopped_echo": [...],
  "report_step": None | "pull_report",
  "report_verdict": "strict" | "lenient",   # strict (get_ratings): report exit 1 = failed.
                                            # lenient (read_only tasks): 0 done, 1 partial, other failed
  "exit": "bat"            # console exit code = old bat semantics, see 6.4
}
```

Default `data`: every step of a task that is not `read_only` has `data: True`, except these, which have `data: False`: every `ootp\winsim.py` step (sims, diagnostics and `--grab` write no app data), every `ootp\cleanup_clones.py` step (clone saves are guarded by `clones.<LG>`, 7.5) and `new_league.py token` (the token file only). A step with `data: False` that comes after the data lock was taken (the cleanup step at the end of a Grind cycle) simply runs while the lock is held. A task whose steps are all `data: False` (sim_tgs, the OOTP tools, the cleanup tasks, `token_set`) never takes the data lock.

Default `drives_ootp`: `True` for winsim steps that click, which are sims (`--runs` without `--dry-run`, and `--sim`) and the `--test-year`, `--test-load` and `--peek-load` diagnostics. `False` for every other step, including `--grab` (it brings OOTP forward but never clicks) and `--dry-run`, `--games`, `--list-windows`.

Argv markers: `@py` = `settings.interp("main")`, `@ml` = `interp("ml")`, `@node` = `interp("node")`. Placeholders in `{}` are filled from inputs and settings: `{league}`, `{slug}`, `{basis}`, `{name}`, `{ootp_save}`, `{ootp_version}`, `{years}`, `{runs}`, `{orgs}`, `{saved_games:26}` (= `saved_games_raw("26")`), `{saved_games:27}`, `{id}` (New League id), `{spec}` (job folder spec file), `{precheck}` (job folder precheck file), `{job_dir}` (this job's folder), `{control}` (the control folder, 3.1). Script paths keep the bats' backslashes and quoting-free tokens: the argv is passed as a list, so the child sees exactly what the bat passed. The cwd of every step is the repo root.

### 3.4 Catalog JSON (`run_task.py --list-json`; A produces, B serves, C renders)

```json
{
  "schema": 1,
  "generated": "2026-10-01T21:00:00",
  "groups": [{"id": "everyday", "title": "Everyday"}],
  "tasks": [ { "id": "...", "title": "...", "description": "...", "group": "...", "leagues": [],
               "bat": "...", "flags": {}, "locks": [], "time": "...", "inputs": [], "stop_modes": [],
               "steps": [{"id": "...", "title": "...", "writes_app_data": true, "data": true,
                          "app_leagues": ["TGS"], "argv": ["python", "..."]}] } ],
  "leagues": [ {"id": "TGS", "name": "TGS", "type": "statsplus", "enabled": true, "pending": false,
                "added_by_wizard": false, "in_app": true, "update_task": "update.TGS",
                "token_line": "TGS="} ],
  "state": {
    "tokens": {"TGS": true, "BLM": true},
    "ootp_installs": {"26": {"path": "C:\\OOTP 26\\data\\saved_games", "exists": true}},
    "ratings_db_exists": true,
    "settings_local": false,
    "settings_error": null,
    "watch_files": ["C:\\...\\tgs-viz\\tools\\settings.defaults.json", "C:\\...\\settings.local.json",
                    "C:\\...\\StatsPlus Tokens.txt", "C:\\...\\tgs-viz\\backtest\\ratings_history.db",
                    "C:\\...\\tgs-viz\\public\\data\\leagues.json"]
  },
  "app_config": { "leagues": { "TGS": {"name": "TGS", "my_org": "Chicago Cubs"} } }
}
```

- `tasks[].steps[].argv` is the resolved argv for display (no secrets ever appear in argv).
- `state.tokens` = `bool(statsplus_token.token_for(slug))` per enabled online league. It reads the token file in process and never calls `ensure_file()`. Values never leave the process.
- `token_line` = the exact line the user edits in StatsPlus Tokens.txt: `slug.upper() + "="` (the file is keyed by slug, statsplus_token.py:138 and :288).
- `added_by_wizard` = the league's settings entry exists only in settings.local.json (not in the defaults). Only these leagues get a `remove_league.<ID>` task.
- `in_app` = the id is in `public/data/leagues.json`.
- `state.watch_files`: B stats these (size and mtime) on every `GET /__tgs/catalog` and every 5 s, and rebuilds the catalog when one changes. So a token pasted in Notepad shows up in the run forms within 5 s.
- Hidden tasks stay in the catalog with `flags.hidden: true`; C leaves them off the cards. B looks every task up in this list, so the wizard can start `new_league`. `selftest.*` appear only with `--selftest`.
- On `SettingsError`, `--list-json` still exits 0 and prints a catalog with only `doctor`, `leagues: []`, and `state.settings_error` = the plain message. The page then shows the Setup page with the error and the "Reset local settings" button (8.5).
- `--list-json` must finish in under 2 seconds and must not import winsim, numpy, openpyxl or statsplus.py.

### 3.5 New CLI flags D adds that A's tasks call

| Script | Flag | Behavior |
|---|---|---|
| `ootp/cleanup_clones.py` | `--dry-run` | Print the same candidate list, then `  (dry run - nothing deleted)` and exit 0. Never calls `input()`. |
| `tgs-viz/ingest/refresh.py` | `--calib <TGS or BLM>` | Calibration league for pricing (default = `--league`). Section 11.4. |
| `tgs-viz/ingest/draft.py` | `--calib <TGS or BLM>` | Same, in `main()` and `dispersal_main()`. |
| `tgs-viz/ingest/pull_report.py` | `--leagues A,B` | Report only these leagues. No flag = TGS and BLM (today). |
| `tgs-viz/ingest/statsplus_token.py` | `--have <ID>` for any enabled online league | Today only TGS and BLM (statsplus_token.py:308-318). |
| `ootp/winsim.py` | `--reset-input` | Calls `reset_input()` (winsim.py:263: releases Ctrl, Shift, Alt, Win and the left mouse button) and exits 0. Opens no window and clicks nothing. run_task runs it after it kills a step that drives OOTP. |
| `tgs-viz/tools/new_league.py` | subcommands | Section 12.2. |
| `tgs-viz/tools/doctor.py` | `--json` | Section 13. |

---

## 4. Task list

### 4.1 Groups

| id | Title |
|---|---|
| `everyday` | Everyday |
| `leagues` | Your leagues (generated `update.<ID>` tasks) |
| `season` | Season end |
| `calibration` | Calibration and clone sims |
| `dev` | DEV research league and ML |
| `ootp` | OOTP tools |
| `setup` | Setup and checks |
| `selftest` | Self tests (only with `TGS_SELFTEST=1`) |

### 4.2 Notation used below

```
@py "path" args        [policy]  {app}
```
`[collect TAG]`, `[fail]`, `[ignore]`, `[probe flag]`, `[stopafter]`, `[report]` (a final report step: its exit code feeds the job verdict through `report_verdict`, never FAILS). `{app}` = `writes_app_data`; its `app_leagues` follow the table in 9.3. `{nodata}` = `data: False` (3.3 lists which steps have it). `excel_check <folder>` = a job-mode-only step that looks for Excel lock files of `The Sheet Hitters.xlsx` and `The Sheet Pitchers.xlsx` in that folder (7.3). Text in `console:` lines is printed by run_task in console mode at that point. Banner and echo text is ported from the legacy bat as cmd prints it, carets removed (14.1); section 6.5 lists the only allowed text changes. Locks, `read_only` and `needs_archive` for every task are in 4.10.

### 4.3 Tasks that replace a bat (18)

#### get_ratings (Get StatsPlus Ratings.bat), group everyday, flags network, secret_inputs, writes_app_data; time "5 to 15 minutes"

Inputs (job mode; console asks them inside the prelude):
- `sessionid` secret, optional. `ask_when: {"any": [{"no_token": "TGS"}, {"no_token": "BLM"}]}`.
- `csrftoken` secret, optional. `ask_when: {"all": [{"any": [{"no_token": "TGS"}, {"no_token": "BLM"}]}, {"any": [{"all": [{"no_token": "TGS"}, {"no_token": "BLM"}]}, {"input_nonblank": "sessionid"}]}]}`.

Steps:
```
prelude cookie_pair(TGS, BLM)     (6.2; probes below are real steps)
  @py "tgs-viz\ingest\statsplus_token.py" --have TGS                         [probe tok_TGS]
  @py "tgs-viz\ingest\statsplus_token.py" --have BLM                         [probe tok_BLM]
@py "tgs-viz\ingest\refresh.py" --statsplus --league TGS --write             [collect TGS-ratings] {app}
@py "tgs-viz\ingest\draft.py" --league TGS --write                           [collect TGS-draft] {app}
@py "tgs-viz\ingest\r5.py" --league TGS --write                              [collect TGS-r5] {app}
@py "tgs-viz\ingest\refresh.py" --statsplus --league BLM --slug blm --write  [collect BLM-ratings] {app}
@py "tgs-viz\ingest\draft.py" --league BLM --slug blm --write                [collect BLM-draft] {app}
@py "tgs-viz\ingest\r5.py" --league BLM --write                              [collect BLM-r5] {app}
@py "tgs-viz\engine\agecurve_fit.py" --league TGS --write                    [collect TGS-agecurve] {app}
@py "tgs-viz\engine\agecurve_fit.py" --league BLM --write                    [collect BLM-agecurve] {app}
@py "tgs-viz\backtest\ratings_db.py" --export                                [collect rating-trends] {app}
@py "tgs-viz\backtest\dev_signals.py" --league TGS --write                   [collect TGS-devsignals] {app}
@py "tgs-viz\backtest\dev_signals.py" --league BLM --write                   [collect BLM-devsignals] {app}
@ml "tgs-viz\backtest\ml\dataset.py" --basis TGS --score-only --write        [collect TGS-ml-rows]
@ml "tgs-viz\backtest\ml\dataset.py" --basis BLM --score-only --write        [collect BLM-ml-rows]
@ml "tgs-viz\backtest\ml\score.py" --league TGS --write                      [collect TGS-ml-score] {app}
@ml "tgs-viz\backtest\ml\score.py" --league BLM --write                      [collect BLM-ml-score] {app}
console: FAILS block (Get StatsPlus Ratings.bat:127-130)
@py "tgs-viz\ingest\pull_report.py"                                          [report]
```
Cookie scope: every step after the prelude (the bat keeps `STATSPLUS_COOKIE` set to the end). Job verdict (`report_verdict: strict`): `failed` when `pull_report` exits 1 (nothing fresh), else `partial` when FAILS is not empty, else `done`. Live refresh: TGS player files reach the open app once, after `TGS-ml-score`; BLM's once, after `BLM-ml-score` (9.3), so the app never shows new dev signals next to old ML numbers.

#### get_history (Get StatsPlus History.bat), group season, flags network, secret_inputs, long, writes_app_data; time "Minutes to about 2 hours (StatsPlus decides the waits)"

The time label follows the code, not the stale banner (critic item 22: `RATE_GAP = 0.0`, `MIN_PAUSE = 20 s`, statsplus_history.py:228-233).

Inputs:
- `league` choice, required. Choices = leagues in `settings.history_settings()` (TGS, BLM). Console: `prompt: "Which league? Type TGS or BLM, then press Enter:"`, `loop_until_valid: true`, `invalid_echo: [" Please type TGS or BLM."]`, case-insensitive. For more than two choices the prompt lists them all.
- `sessionid`, `csrftoken` secret, optional, `ask_when: {"no_token_input": "league"}`.

Steps:
```
prelude cookie_single({league})
  @py "tgs-viz\ingest\statsplus_token.py" --have {league}                   [probe tok]
@py "tgs-viz\ingest\statsplus_history.py" --league {league} --slug {slug} --write   [handler history_codes]   env cookie THIS STEP ONLY
@py "tgs-viz\engine\agecurve_fit.py" --league {league} --write              [collect {league}-agecurve] {app}
@py "tgs-viz\backtest\ratings_db.py" --export                               [collect rating-trends] {app}
@py "tgs-viz\backtest\dev_signals.py" --league {league} --write             [collect {league}-devsignals] {app}
@ml "tgs-viz\backtest\ml\dataset.py" --basis {league} --score-only --write  [collect {league}-ml-rows]
@ml "tgs-viz\backtest\ml\score.py" --league {league} --write                [collect {league}-ml-score] {app}
```
`history_codes`: exit 0 continues. Exit 2, 3, 6, 7, 8, 9, 10 prints the matching STOPPED text (Get StatsPlus History.bat:110-166; code 3 has a token variant when `tok` is set), then the "skipped" lines (:162-166), skips every later step, job status `failed`. Any other nonzero exit adds `{league}-history` to FAILS and continues.

#### bank_season (Bank Season.bat), group season, flags network; time "1 to 3 minutes"

```
@py "tgs-viz\backtest\fetch_actuals.py" --league TGS --write                        [collect TGS-actuals]
@py "tgs-viz\backtest\snapshot_projections.py" --league TGS --write                 [collect TGS-snapshot]
@py "tgs-viz\backtest\fetch_actuals.py" --league BLM --slug blm --write             [collect BLM-actuals] fail_echo "  (warning: BLM actuals failed - its API may differ; continuing)"
@py "tgs-viz\backtest\snapshot_projections.py" --league BLM --slug blm --write      [collect BLM-snapshot] fail_echo "  (warning: BLM snapshot failed - continuing)"
```
Finish: "Done" lines (:49-52) or "NOT done:" + FAILS (:55-57).

#### bank_dev (Bank Dev Seasons.bat), group dev, flags heavy, long, writes_app_data; time "Hours (retrains the ML models; needs about 13 GB of memory)"

All steps `[fail]`, exactly the bat's list:
```
@py "tgs-viz\backtest\dump_vintages.py" --league DEV --write
@py "tgs-viz\backtest\ratings_db.py" --export --league DEV                          {app}
@py "tgs-viz\engine\agecurve_fit.py" --league DEV --calib BLM --no-guard --write    {app}
@py "tgs-viz\backtest\ml\reprice.py" --calib TGS
@py "tgs-viz\backtest\dev_odds.py" --write                                          {app}
@py "tgs-viz\backtest\dev_rating_odds.py" --write                                   {app}
@py "tgs-viz\backtest\dev_signals.py" --league TGS --write                          {app}
@py "tgs-viz\backtest\dev_signals.py" --league BLM --write                          {app}
@ml "tgs-viz\backtest\ml\dataset.py" --basis TGS --write
@ml "tgs-viz\backtest\ml\dataset.py" --basis BLM --write
@ml "tgs-viz\backtest\ml\peak.py" fit-final --basis TGS
@ml "tgs-viz\backtest\ml\path.py" fit-final --basis TGS
@ml "tgs-viz\backtest\ml\peak.py" fit-final --basis BLM
@ml "tgs-viz\backtest\ml\path.py" fit-final --basis BLM
@ml "tgs-viz\backtest\ml\predict.py" check --basis TGS
@ml "tgs-viz\backtest\ml\predict.py" check --basis BLM
@ml "tgs-viz\backtest\ml\score.py" --league TGS --write                             {app}
@ml "tgs-viz\backtest\ml\score.py" --league BLM --write                             {app}
@py "tgs-viz\extract_data.py" --manifest-only                                       {app}
console and job log, success only, one line per X in settings.extra_leagues() (allowed text change 6 in 6.5),
  printed just before the Done block:
  "  <name of X> still uses its old dev numbers. Run Update <name of X> to refresh them."
  Today this renders once: "  Regular Game still uses its old dev numbers. Run Update Regular Game to refresh them."
```
Critic item 10 (the bat rescores TGS and BLM only, so RG keeps old odds and old models) is handled by the reminder line, by `dev_rescore` and by `retrain_ml` (4.6), not by new steps here. Reason (user setup review, item 7): the bat never touched RG, and rescoring RG would change RG's Starter %, Star % and Proj Potential after a bat that never did. The user may choose otherwise (section 19, user decisions).

#### grind_tgs (Grind TGS.bat), group calibration, flags endless, drives_ootp, needs_excel_closed, heavy, writes_app_data; time "Runs until you stop it; about 75 minutes per cycle"

Inputs: `ootp_ready` confirm, required in job mode: "OOTP 26 is open inside a league other than Baseline, and nothing else needs the mouse." `runs` text int 1-50, default 10, no console prompt.

```
gate (console: pause, Grind TGS.bat:22)
loop from winsim (console: CYCLE echo, Grind TGS.bat:27-29)
@py "ootp\winsim.py" --league TGS --runs {runs}                                     [stopafter] {nodata} drives_ootp; echo on fail: "  winsim reported a problem - recalibrating what finished, then stopping."
   (the data lock is taken here, before calibrate, and released at the end of the cycle: 7.5)
@py "tgs-viz\engine\calibrate.py" --csv-dir "tgs-viz\engine\calib\TGS" --dumps "{saved_games:26}/*tgs*.lg" --ratings-dir "tgs-viz\engine\calib\TGS" --json "tgs-viz\engine\calib\TGS\constants-latest.json" --archive-dir "tgs-viz\engine\calib\TGS"   [fail]
excel_check "The Sheets TGS"
@py "tgs-viz\ingest\sync_datapoints.py" --league TGS --calib "tgs-viz\engine\calib\TGS\constants-latest.json" --write --yes   [fail]
@py "tgs-viz\engine\hitter_tails_fit.py" --league TGS          [fail]
@py "tgs-viz\engine\fielding_curves_fit.py" --league TGS       [fail]
@py "tgs-viz\engine\currency_fit.py" --league TGS              [fail]
@py "tgs-viz\engine\scurve_fit.py" --league TGS                [ignore]
@py "tgs-viz\engine\promote_scurves.py" --league TGS           [ignore]
@py "tgs-viz\engine\extract_sheet.py" TGS                      [ignore]
@py "tgs-viz\engine\extract_pitchers.py" TGS                   [ignore]
@py "tgs-viz\engine\agecurve_fit.py" --league TGS --write      [ignore] {app}
@py "tgs-viz\engine\export_calibration.py" --league TGS --write   [ignore] {app}
@py "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league TGS --write   [fail] {app}
@py "ootp\cleanup_clones.py" --league TGS --junk --yes         [ignore]
end of cycle: if stopafter -> finish "stopped" (Grind TGS.bat:68-75, exit 1); else next cycle
```
Default `{runs}` renders as `10` and `{saved_games:26}` as `C:/OOTP 26/data/saved_games`, so argv equals the bat (Grind TGS.bat:30, :38).

#### grind_blm (Grind BLM.bat)

Same shape as grind_tgs (including `{nodata}` on winsim and `excel_check "The Sheets BLM"` before sync) with: `ootp_ready` text "OOTP 27 is open inside a league other than \"6\" ...", winsim `--league BLM --runs {runs}`, calibrate `--csv-dir "tgs-viz\engine\calib\BLM" --dumps "{saved_games:27}/0blm*.lg" --ratings-dir "tgs-viz\engine\calib\BLM" --json "tgs-viz\engine\calib\BLM\constants-latest.json" --archive-dir "tgs-viz\engine\calib\BLM"`, sync `--league BLM --calib "tgs-viz\engine\calib\BLM\constants-latest.json" --write --yes`, the three fits with `--league BLM` `[fail]`, then `scurve_fit.py --league BLM` `[ignore]` and NO promote step (Grind BLM.bat:51-54), `extract_sheet.py BLM`, `extract_pitchers.py BLM`, `agecurve_fit.py --league BLM --write`, `export_calibration.py --league BLM --write` (all `[ignore]`), `refresh.py --statsplus --from-cache --league BLM --slug blm --write` `[fail]`, `cleanup_clones.py --league BLM --junk --yes` `[ignore]`. `{saved_games:27}` renders as `%USERPROFILE%` expanded, identical to what cmd passes today.

#### recalibrate_tgs (Recalibrate TGS.bat), group calibration, flags needs_excel_closed, writes_app_data; time "1 to 3 minutes plus your answers"

```
gate (console: pause :20; job: Start button only)
@py "tgs-viz\engine\calibrate.py" ...TGS args as grind_tgs...                       [fail]
excel_check "The Sheets TGS"
@py "tgs-viz\ingest\sync_datapoints.py" --league TGS --calib "tgs-viz\engine\calib\TGS\constants-latest.json" --write   [fail]
     job: preview  @py ...sync_datapoints.py --league TGS --calib "...constants-latest.json"
          apply    @py ...sync_datapoints.py --league TGS --calib "...constants-latest.json" --write --yes
          count_regex ^\s+(\d+) cell\(s\) will change ; question "Apply these changes to The Sheets TGS?"
@py "tgs-viz\engine\hitter_tails_fit.py" --league TGS       [fail]
@py "tgs-viz\engine\fielding_curves_fit.py" --league TGS    [fail]
@py "tgs-viz\engine\currency_fit.py" --league TGS           [fail]
@py "tgs-viz\engine\scurve_fit.py" --league TGS             [ignore]
@py "tgs-viz\engine\promote_scurves.py" --league TGS        [ignore]
@py "tgs-viz\engine\export_calibration.py" --league TGS --write   [fail] {app}
@py "tgs-viz\engine\extract_sheet.py" TGS                   [ignore]
@py "tgs-viz\engine\extract_pitchers.py" TGS                [ignore]
@py "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league TGS --write   [fail] {app}
@py "ootp\cleanup_clones.py" --league TGS --junk            [ignore]
     job: preview  @py "ootp\cleanup_clones.py" --league TGS --junk --dry-run
          apply    @py "ootp\cleanup_clones.py" --league TGS --junk --yes
          count_regex will DELETE (\d+) clone league ; question "Delete these clone saves? Check the folder names above first."
          The prompt's details are the preview lines, which name every folder (cleanup_clones.py:97-107).
```

#### recalibrate_blm (Recalibrate BLM.bat), group season, flags network, needs_excel_closed, writes_app_data; time "A few minutes plus your SP/RP paste"

Description must say it runs only after the BLM season ends: `metadata_inputs.py` refuses in game months 4 to 9 (critic item 23, metadata_inputs.py:132-136).

```
gate (console: pause :27)
@py "tgs-viz\ingest\metadata_inputs.py" --league BLM --out "tgs-viz\engine\calib\BLM\metadata_inputs" --stage auto   [fail]
gate paste_reminder (console: REMINDER box :36-40 + pause :41; job: prompt kind "gate",
     text "Paste 'SP Data' (as starter) and 'RP Data' (as reliever) into The Sheets BLM\25 Metadata.xlsx, save, and close Excel.",
     choices Continue / Stop)
@py "tgs-viz\ingest\metadata_inputs.py" --league BLM --out "tgs-viz\engine\calib\BLM\metadata_inputs" --stage roles --accept-paste   [fail]
@py "tgs-viz\engine\metadata_calibrate.py" --inputs-dir "tgs-viz\engine\calib\BLM\metadata_inputs" --json "tgs-viz\engine\calib\BLM\metadata-latest.json"   [fail]
@py "tgs-viz\engine\calibrate.py" --csv-dir "tgs-viz\engine\calib\BLM" --dumps "{saved_games:27}/0blm*.lg" --ratings-dir "tgs-viz\engine\calib\BLM" --json "tgs-viz\engine\calib\BLM\constants-latest.json" --archive-dir "tgs-viz\engine\calib\BLM"   [fail]
excel_check "The Sheets BLM"
@py "tgs-viz\ingest\sync_datapoints.py" --league BLM --calib "tgs-viz\engine\calib\BLM\constants-latest.json" --metadata-calib "tgs-viz\engine\calib\BLM\metadata-latest.json" --write --yes   [fail]
@py "tgs-viz\engine\hitter_tails_fit.py" --league BLM      [fail]
@py "tgs-viz\engine\fielding_curves_fit.py" --league BLM   [fail]
@py "tgs-viz\engine\currency_fit.py" --league BLM          [fail]
@py "tgs-viz\engine\scurve_fit.py" --league BLM            [ignore]
@py "tgs-viz\engine\promote_scurves.py" --league BLM       [ignore]
@py "tgs-viz\engine\export_calibration.py" --league BLM --write   [fail] {app}
@py "tgs-viz\engine\extract_sheet.py" BLM                  [ignore]
@py "tgs-viz\engine\extract_pitchers.py" BLM               [ignore]
@py "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league BLM --slug blm --write   [fail] {app}
@py "ootp\cleanup_clones.py" --league BLM --junk           [ignore]   job: preview/confirm/apply as recalibrate_tgs
```
The bat expands `%INPUTS%`, `%META%`, `%CONST%` (:28-30); the registry writes the expanded paths.

#### sim_dev (Sim Dev League.bat), group dev, flags drives_ootp, long, writes_app_data; time "Depends on OOTP sim speed"

Inputs: `years` text int, default "5", `from_argv: 1` (the bat's `%~1`; console passes it through unvalidated, as the bat did; job mode validates 1 to 50). `ootp_ready` confirm (job): "OOTP 27 is open inside a league (any league; the main menu is not enough). In DEV TESTS, Export CSV files after each simulated season is on."

```
gate (console: pause :38)
@py "ootp\winsim.py" --league DEV --sim --years {years}        [fail] {nodata} drives_ootp
exists_check "tgs-viz\backtest\dump_vintages.py" (missing: echo :48, then fail)
@py "tgs-viz\backtest\dump_vintages.py" --league DEV --write   [fail]
@py "tgs-viz\backtest\ratings_db.py" --export --league DEV     [fail] {app}
@py "tgs-viz\extract_data.py" --manifest-only                  [fail] {app}
```

#### sync_metadata (Sync Metadata.bat), group season, flags needs_excel_closed; time "Under a minute plus your answers"

```
excel_check "The Sheets TGS"
@py "tgs-viz\ingest\sync_datapoints.py" --league TGS --calib "tgs-viz\engine\calib\TGS\constants-latest.json" --write   [fail]
     job: preview/confirm/apply (as recalibrate_tgs), question "Apply these changes to The Sheets TGS?"
excel_check "The Sheets BLM"
when exists "tgs-viz\engine\calib\BLM\metadata-latest.json":
@py "tgs-viz\ingest\sync_datapoints.py" --league BLM --calib "tgs-viz\engine\calib\BLM\constants-latest.json" --metadata-calib "tgs-viz\engine\calib\BLM\metadata-latest.json" --write   [fail]
else:
@py "tgs-viz\ingest\sync_datapoints.py" --league BLM --calib "tgs-viz\engine\calib\BLM\constants-latest.json" --write   [fail]
     job (both BLM variants): preview/confirm/apply, question "Apply these changes to The Sheets BLM?"
@py "tgs-viz\engine\extract_sheet.py" TGS      [ignore]
@py "tgs-viz\engine\extract_pitchers.py" TGS   [ignore]
@py "tgs-viz\engine\extract_sheet.py" BLM      [ignore]
@py "tgs-viz\engine\extract_pitchers.py" BLM   [ignore]
```

#### dispersal_board (Update Dispersal Board.bat), group everyday, flags network, writes_app_data; time "Under a minute"

Input: `orgs` text, no console prompt. Default = the entries of `leagues.TGS.dispersal_orgs` joined with `,` and no spaces between entries, which renders exactly `Atlanta Hammers,Detroit Tigers,San Francisco Giants,Seattle Mariners` (Update Dispersal Board.bat:19).
```
@py "tgs-viz\ingest\draft.py" --league TGS --orgs "{orgs}" --write   [fail]  {app}
```
Finish: "Done" (:23) or "NOT updated" (:27). No `exit /b` in the bat: console exit code = draft.py's code (6.4).

#### draft_board (Update Draft Board.bat), group everyday, flags network, writes_app_data; time "1 to 2 minutes"

```
@py "tgs-viz\ingest\draft.py" --league TGS --write              [collect TGS] {app}
@py "tgs-viz\ingest\draft.py" --league BLM --slug blm --write   [collect BLM] {app}
```

#### update.RG (Update Regular Game.bat): generated `local_export` task, see 4.5. Its default render must equal the bat except the allowlisted `--game 27 --calib BLM` (14.1).

#### ootp_check_26 (ootp/1), group ootp; time "Seconds"
```
@py "ootp\winsim.py" --game 26 --list-windows   [ignore]
@py "ootp\winsim.py" --game 26 --grab           [ignore]
```
`--grab` brings OOTP to the front with an Alt tap (winsim.py:1413-1415, :204-218) and clicks nothing, so the task holds the `ootp` lock (4.10) but has no "Hands off" countdown. It is the first live test of window focus from a page job (16, step 11).
#### ootp_grab_menu_26 (ootp/2), group ootp, flags drives_ootp; time "About 10 seconds"
```
gate (console: pause :14)
@py "ootp\winsim.py" --game 26 --grab --delay 6   [ignore]
```
Job mode shows: "After you press Start, you have 6 seconds to open the menu in OOTP." No "Hands off" countdown here: the user must touch OOTP.
#### sim_tgs_preview (ootp/3), group calibration; time "Seconds"
```
@py "ootp\winsim.py" --league TGS --runs 1 --dry-run   [ignore]
```
#### sim_tgs (ootp/4), group calibration, flags drives_ootp, long; time "About 75 minutes"
Inputs: `ootp_ready` confirm (job), `runs` int default 10.
```
gate (console: pause :19)
@py "ootp\winsim.py" --league TGS --runs {runs}   [ignore] {nodata} drives_ootp
```
#### ootp_test_year_26 (ootp/TEST year picker), group ootp, flags drives_ootp; time "Under a minute"
```
gate (console: pause :15)
@py "ootp\winsim.py" --league TGS --test-year   [ignore] {nodata} drives_ootp
```

### 4.4 Conditions (A implements in conditions.py, C mirrors in inputConditions.js)

JSON objects, one key each:

| Condition | True when |
|---|---|
| `{"no_token": "TGS"}` | `state.tokens.TGS` is false (console mode: the probe flag `tok_TGS` is not set) |
| `{"no_token_input": "league"}` | the league chosen in input `league` has no token |
| `{"input_nonblank": "sessionid"}` | that input is a non-empty string after strip |
| `{"exists": "rel\\path"}` | the path exists under the repo root (Python only; never in `ask_when`) |
| `{"flag": "stopafter"}` | runner flag set (Python only) |
| `{"all": [c, ...]}`, `{"any": [c, ...]}`, `{"not": c}` | logic |

Shared cases: `tgs-viz/tools/tests/fixtures/conditions_cases.json` (A owns it). A list of `{"name", "condition", "state": {"tokens": {...}}, "inputs": {...}, "flags": {...}, "expect": bool, "python_only": bool}`. It holds at least every row above, the two Get StatsPlus Ratings `ask_when` conditions (4.3) for the four token states with `sessionid` blank and given, and `no_token_input` for each league choice. C's test skips the `python_only` cases (`exists`, `flag`).

### 4.5 Generated per-league tasks (one per enabled league in settings)

#### `update.<ID>`, type `statsplus` (TGS, BLM, new online leagues), group leagues, flags network, secret_inputs, writes_app_data

Inputs: `sessionid`, `csrftoken` with `ask_when: {"no_token": "<ID>"}`.
```
prelude cookie_single(<ID>): @py "tgs-viz\ingest\statsplus_token.py" --have <ID>   [probe tok]
@py "tgs-viz\ingest\refresh.py" --statsplus --league <ID> --slug <slug> [--calib <basis> when basis != ID] --write   [collect <ID>-ratings] {app}
@py "tgs-viz\ingest\draft.py" --league <ID> --slug <slug> [--calib <basis>] --write   [collect <ID>-draft] {app}
@py "tgs-viz\ingest\r5.py" --league <ID> --write                    [collect <ID>-r5] {app}   when ootp_save is set
@py "tgs-viz\engine\agecurve_fit.py" --league <ID> --write          [collect <ID>-agecurve] {app}   when basis == ID
@py "tgs-viz\backtest\ratings_db.py" --export --league <ID>         [collect rating-trends] {app}
@py "tgs-viz\backtest\dev_signals.py" --league <ID> --write         [collect <ID>-devsignals] {app}
@ml "tgs-viz\backtest\ml\dataset.py" --basis <ID> --score-only --write   [collect <ID>-ml-rows]
@ml "tgs-viz\backtest\ml\score.py" --league <ID> --write            [collect <ID>-ml-score] {app}
@py "tgs-viz\ingest\pull_report.py" --leagues <ID>                  [report]
```
Cookie scope: every step after the prelude.

#### `update.<ID>`, type `local_export` (RG and new local saves), group leagues, flags writes_app_data
```
@py "tgs-viz\ingest\export_league.py" --league <ID> --name "<name>" --save "<ootp_save>" --game <ootp_version> --calib <basis> --write   [collect players] {app}
@py "tgs-viz\backtest\dev_signals.py" --league <ID> --write                  [collect dev-signals] {app}
@ml "tgs-viz\backtest\ml\dataset.py" --basis <ID> --score-only --write      [collect ml-rows]
@ml "tgs-viz\backtest\ml\score.py" --league <ID> --write                    [collect ml-score] {app}
```
Banner and echo for RG = Update Regular Game.bat text. For a new league, A writes the same text with the league's name.

#### `update.<ID>`, type `dev` (DEV and new dev leagues), group dev, flags writes_app_data; time "About 20 seconds per new season"
```
@py "tgs-viz\backtest\dump_vintages.py" --league <ID> --write     [fail]
@py "tgs-viz\backtest\ratings_db.py" --export --league <ID>       [fail] {app}
@py "tgs-viz\tools\new_league.py" register-manifest --league <ID> [fail] {app}
```
`register-manifest` replaces `extract_data.py --manifest-only` for new tasks (critic item 13); the bat tasks keep `--manifest-only` for equivalence. It does exactly this and nothing else: when `tgs-viz/public/data/<ID>/rating_trends.json` exists, `extract_data.upsert_manifest(path, [extract_data.build_manifest_entry(ID, name=N)])`, where `N` = the name already in leagues.json for that id, else the settings `name` (extract_data.py:357-366, :396-406). `build_manifest_entry` detects the features from the folder, so DEV keeps `"players": false` and all five flags. Any other builder could leave a flag out, and the app sets a missing flag to true (leagues.js:20, :47), which would send DEV down the player path and show "No player data" (App.jsx:370-372). D's test proves the bytes of leagues.json stay identical for DEV, CRLF included (14.3).

#### `sim_dev.<ID>`, type `dev`, ID != DEV, flags drives_ootp, long
Inputs `years` (default from `ootp_profile.years`, else 5), `ootp_ready` confirm.
```
gate
@py "ootp\winsim.py" --league <ID> --sim --years {years}   [fail] {nodata} drives_ootp
then the three update.<ID> steps
```

#### type `clone` (new clone profiles): `sim_clones.<ID>`, `sim_clones_preview.<ID>`, `cleanup_clones.<ID>`
```
sim_clones.<ID>          gate; @py "ootp\winsim.py" --league <ID> --runs {runs}   [fail] {nodata} flags drives_ootp, long
sim_clones_preview.<ID>  @py "ootp\winsim.py" --league <ID> --runs 1 --dry-run   [ignore]
cleanup_clones.<ID>      @py "ootp\cleanup_clones.py" --league <ID> --junk         preview/confirm/apply (--dry-run / --yes)
```

### 4.6 Tasks with no bat today

| id | Group | Steps | Flags, notes |
|---|---|---|---|
| `retrain_ml` | dev | bank_dev's 10 ML steps in bat order (dataset TGS, dataset BLM, peak TGS, path TGS, peak BLM, path BLM, predict TGS, predict BLM, score TGS, score BLM) `[fail]`, then for each extra league X: `dataset --basis X --score-only --write`, `score --league X --write` `[collect]` | heavy, long, writes_app_data. "Hours; about 13 GB of memory (STATUS.md:40)" |
| `retrain_ml.TGS` | dev | `@ml dataset.py --basis TGS --write`, `@ml peak.py fit-final --basis TGS`, `@ml path.py fit-final --basis TGS`, `@ml predict.py check --basis TGS`, `@ml score.py --league TGS --write` `[fail]`; extras whose basis is TGS `[collect]` | heavy, long |
| `retrain_ml.BLM` | dev | same with BLM; extras whose basis is BLM (RG) `[collect]` | heavy, long |
| `dev_rescore` | dev | for L in TGS, BLM, extras: `dev_signals.py --league L --write`, `@ml dataset.py --basis L --score-only --write`, `@ml score.py --league L --write`, all `[collect L-...]` | writes_app_data. "No retraining; a few minutes" |
| `bank_market_fit` | everyday | input `league` choice: `all` (default) or one player league. One step per league: `@node "tgs-viz\scripts\bank_market_fit.mjs" <L>` `[collect <L>-market]` {app} | The only writer of `<LG>/market_fit.json` (critic item 11). Never runs without a league argument (DEV has no players) |
| `iafa_board` | everyday | input `league` choice (online leagues with `ootp_save`). `@py "tgs-viz\ingest\iafa.py" --league {league} --write` `[fail]` {app} | Today a typed command only |
| `parks_update` | season | `@py "tgs-viz\ingest\parks.py" --write` `[fail]`; `@py "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league TGS --write` `[collect TGS-ratings]`; same for BLM with `--slug blm` `[collect BLM-ratings]` | network (refresh may refetch team names), writes_app_data. Needed after a `my_team` change (critic item 16) |
| `pull_report` | everyday | `@py "tgs-viz\ingest\pull_report.py"` `[report]`, `report_verdict: lenient` | "Data date report: what the app is serving". Read only. Exit 1 (nothing pulled in the last 30 minutes) ends as "Finished with problems", not Failed |
| `cleanup_clones.TGS`, `cleanup_clones.BLM` | calibration | `@py "ootp\cleanup_clones.py" --league <L> --junk` with preview/confirm/apply | Console mode asks with `input()` as today |
| `sim_blm_preview` | calibration | `@py "ootp\winsim.py" --league BLM --runs 1 --dry-run` `[ignore]` | Read only |
| `token_check` | setup | `@py "tgs-viz\ingest\statsplus_token.py" --check` `[fail]` | network. Never run automatically |
| `token_set` | setup | inputs: `league` choice (enabled online leagues, by name), `token` secret, required. `@py "tgs-viz\tools\new_league.py" token --league {league}` with env `TGS_NL_TOKEN` = the secret, this step only `[fail]` | "Replace a StatsPlus token". Tokens expire every 90 days (statsplus_token.py:33); this saves the new one with the same code as the wizard (`statsplus_token.save`, :272-282). The form names the exact line it writes (`token_line`, 3.4). B rebuilds the catalog when the token file changes (3.4) |
| `restore_ratings_db` | setup | `@py "tgs-viz\backtest\vintage_backup.py" --restore` `[fail]` | `flags.hidden` while `state.ratings_db_exists`. The script refuses to overwrite (vintage_backup.py:112-113). The fix task named by the archive check (7.3) and by doctor |
| `doctor` | setup | `@py "tgs-viz\tools\doctor.py"` `[report]`, `report_verdict: lenient` | Read only, no network. Exit 1 (a `fail` row) ends as "Finished with problems" |
| `winsim_games` | ootp | `@py "ootp\winsim.py" --games` `[ignore]` | Lists OOTP installs |
| `dev_test_load` | dev | gate; `@py "ootp\winsim.py" --league DEV --test-load "<DEV.ootp_save>"` `[ignore]` {nodata} drives_ootp | flags drives_ootp. Sim Dev League.bat:26-30 first-run check |
| `dev_test_year` | dev | gate; `@py "ootp\winsim.py" --league DEV --test-year` `[ignore]` {nodata} drives_ootp | flags drives_ootp |
| `new_league` | leagues (`flags.hidden`; started by the wizard) | section 12.3 | Stays in the catalog so `POST /__tgs/jobs` finds it |
| `new_league_cleanup` | leagues (`flags.hidden`; started from a lost New League job's page) | input `job_id` (text, must match the job id pattern in 7.1): `@py "tgs-viz\tools\new_league.py" rollback --spec "{control}\jobs\{job_id}\new_league_spec.json" --precheck "{control}\jobs\{job_id}\precheck.json"` `[fail]` | "Clean up unfinished league" (12.6) |
| `remove_league.<ID>` | leagues | one per league with `added_by_wizard` (3.4): `@py "tgs-viz\tools\new_league.py" remove --league <ID>` `[fail]` {app} | "Remove <name> from the app". Needs a required text input `confirm_id` equal to the id (12.5). Never generated for a league in the committed defaults |

No task ever runs `extract_data.py` without `--manifest-only`. `metadata.json` for TGS and BLM has no safe writer (critic item 11); no task offers one.

### 4.7 Task visibility

A task is in the catalog when every id in `requires_leagues` is an enabled, non-pending settings league. TGS-and-BLM bat tasks require both. `update.RG` requires RG. Generated tasks exist only for enabled, non-pending leagues. Hidden tasks are in the catalog with `flags.hidden: true` (3.4).

### 4.8 Ordering rules the registry must keep (from the bats)

- dev_signals before ML rows and ML score (Get StatsPlus Ratings.bat:116-117).
- agecurve_fit DEV before dev_odds (Bank Dev Seasons.bat:31-33).
- metadata before regressions (Recalibrate BLM.bat:15-19).
- A league's manifest entry only after its player or trends files exist (section 12).

### 4.9 Selftest tasks (A; hidden unless `TGS_SELFTEST=1`)

All steps are `@py "tgs-viz\tools\selftest_steps.py" <action> [args]`.

| id | Behavior |
|---|---|
| `selftest.ok` | One step: prints 5 lines including `é` and `✓`, then a partial line, waits 1 s, then ends the line. Status done |
| `selftest.fail_collect` | 3 steps, step 2 exits 1 (`collect T2`). Status partial, FAILS `T2` |
| `selftest.fail_fast` | 3 steps, step 2 exits 1 (`fail`). Step 3 skipped. Status failed |
| `selftest.confirm` | preview prints `  3 cell(s) will change`; confirm; apply prints `applied` |
| `selftest.confirm_zero` | preview prints `  0 cell(s) will change`; no prompt; apply skipped |
| `selftest.gate` | step, gate prompt (Continue / Stop), step |
| `selftest.long` | 6 steps of `sleep 20` |
| `selftest.loop` | endless: 2 steps of `sleep 5` per cycle |
| `selftest.secret` | secret input `token` (at least 8 characters, 8.5); step env `TEST_SECRET={token}`; the step prints `secret received: yes, length N`, then prints the secret once on purpose, then prints it again split over two writes 200 ms apart with a flush between them. The job log must show `****` in both places |
| `selftest.touch` | input `file` (default `TGS/r5.json`): rewrites `tgs-viz/public/data/<file>` with identical bytes through tmp plus `os.replace` {app} |
| `selftest.corrupt` | copies `tgs-viz/public/data/RG/iafa.json` into the job folder, writes `[{bad` to it, sleeps 8 s, restores the exact bytes {app} |
| `selftest.stdin` | calls `input()`; must print `skipped (no answer)` and exit 0 |
| `selftest.phase` | endless, locks `["ootp"]`, per cycle: step 1 `sleep 8` `{nodata}`, step 2 `sleep 3` (data). Proves that another job can run during step 1 and that step 2 waits for the data lock (15.1, 16 step 7) |
| `selftest.excel` | input `folder` (default `{job_dir}\xl`, created empty): `excel_check` on that folder for `a.xlsx`, then `sleep 1`. A test creates `~$a.xlsx` there first and expects the gate prompt |
| `selftest.hands_off` | one step with `drives_ootp: true` that runs `sleep 1` and touches nothing. Job mode must show the 5-second countdown before it |
| `selftest.archive` | `needs_archive: true`; one step `sleep 0`. Used for the archive check (15.1) |
| `selftest.rollback` | steps `s1` `sleep 1`, `s2` `sleep 20`, `s3` `sleep 0`; `rollback: {"run": ["@py", "tgs-viz\\tools\\selftest_steps.py", "mark", "{job_dir}\\rolled_back"], "until_step": "s3"}` |
| `selftest.leagues` | four `sleep 1` steps with `app_leagues` `["TGS"]`, `["TGS"]`, `["BLM"]`, `[]` and no real writes. Proves `pending_leagues` and `league_done` (15.1) |

Every selftest task holds `task.<id>` and takes the data lock at its first step, like a normal task, unless the row says otherwise.

### 4.10 Locks, read-only and archive flags per task (A puts these in the registry)

Lock names and rules are in 7.5. Every task that is not `read_only` also holds `task.<its id>` for the whole run; the table leaves that out. "Data" says when the task takes the `data` lock. `archive` = `needs_archive`.

| Task | Whole-run locks | Data | read_only | archive |
|---|---|---|---|---|
| `get_ratings`, `get_history`, `update.<statsplus ID>`, `update.<local_export ID>` (RG) | none | from the first step | no | yes |
| `bank_season`, `sync_metadata`, `dispersal_board`, `draft_board`, `iafa_board`, `bank_market_fit` | none | from the first step | no | no |
| `parks_update`, `dev_rescore`, `retrain_ml`, `retrain_ml.TGS`, `retrain_ml.BLM` | none | from the first step | no | yes |
| `bank_dev`, `update.DEV`, `update.<dev ID>` | `dumps.<dev ID>` (DEV for bank_dev) | from the first step | no | yes |
| `grind_tgs`, `grind_blm` | `ootp`, `clones.TGS` / `clones.BLM` | each cycle, from calibrate to the cycle end | no | yes |
| `recalibrate_tgs`, `recalibrate_blm` | `clones.TGS` / `clones.BLM` | from the first step | no | yes |
| `cleanup_clones.TGS`, `cleanup_clones.BLM`, `cleanup_clones.<ID>` | `clones.<L>` | never (`data: False` steps) | no | no |
| `sim_tgs` | `ootp`, `clones.TGS` | never | no | no |
| `sim_clones.<ID>` | `ootp`, `clones.<ID>` | never | no | no |
| `sim_dev`, `sim_dev.<ID>` | `ootp`, `dumps.<dev ID>` | from the first step after winsim | no | yes |
| `ootp_check_26`, `ootp_grab_menu_26`, `ootp_test_year_26`, `dev_test_load`, `dev_test_year` | `ootp` | never | no | no |
| `token_set` | none | never (`data: False`) | no | no |
| `restore_ratings_db` | none | from the first step | no | no (it builds the archive) |
| `new_league`, `new_league_cleanup`, `remove_league.<ID>` | `dumps.<ID>` and `clones.<ID>` of that id when its type has them | from the first step | no | yes |
| `pull_report`, `doctor`, `token_check`, `winsim_games`, `sim_tgs_preview`, `sim_blm_preview`, `sim_clones_preview.<ID>` | none | never | yes | no |

What this allows, in the user's terms:
- Get StatsPlus Ratings, Update Draft Board, Bank Season and the other everyday tasks run while a Grind sims. If the Grind is in its few minutes of recalibrate steps, the pull waits for them, and the Grind's next recalibrate waits for the pull.
- Two tasks that drive OOTP never run together (the user's rule: "One grind at a time, they share your mouse", WHICH BUTTON).
- Recalibrate TGS and Clean up TGS clones refuse while Grind TGS or Sim TGS runs: `cleanup_clones --junk` deletes clones with no complete dumps (cleanup_clones.py:85-89), which includes clones the running sim has not reached yet.
- Bank Dev Seasons and Update DEV refuse while Sim Dev League sims, so they never read a dump OOTP is still writing.

---

## 5. What stays exactly as it is

- Every command, argument, order, condition, error policy and exit code of the 18 bats in console mode (proved in 14.1), including `bank_dev` (no added steps). The documented exceptions: a step that ends with a crash or Ctrl+C code counts as failed (6.4), and a bat refuses or asks only when another task holds a lock it needs (7.5). With no other task running, nothing changes.
- `public/data/leagues.json` content for TGS, BLM, RG, DEV. Nothing in this build writes it except the existing pipeline steps and the New League flow for a new id.
- localStorage keys: `tgs-league`, `tgs-park`, `ptable.hidden.<key>`, the Series Planner store, `tgs-make-it-odds`. New keys use the prefix `tgs-control.`.
- Port 3000 and `npx vite --port 3000 --open` (Launch TGS.bat only adds `--strictPort`, a Node check, a packages check and the port message, 6.6).
- The engine, the research constants, `ootp/leagues.json`, the workbooks.

---

## 6. run_task.py (A)

### 6.1 CLI

```
python tgs-viz/tools/run_task.py <task_id> [positional inputs] [--input name=value ...]
        console mode (the bat wrappers). Inherits the console. Asks prompts with input().
python tgs-viz/tools/run_task.py --launch <job_dir>
        job mode, first hop: what B spawns (8.7). Starts the runner (--job) as a new detached process
        that breaks away from any Windows job object, then exits 0. When that start fails it writes one
        line to runner.log and exits 1.
python tgs-viz/tools/run_task.py --job <job_dir>
        job mode, the runner. Reads <job_dir>/request.json. Never reads stdin.
python tgs-viz/tools/run_task.py --plan <task_id> [--mode console|job] [--inputs-json JSON] [--assume-json JSON]
        prints the plan as JSON; runs nothing. --assume-json: {"exit_codes": {"<step_id>": n or [n per cycle]},
        "flags": {"tok_TGS": true}, "exists": {"rel\\path": true}, "answers": {"<input>": "..."},
        "confirm": {"<step_id>": "yes"|"no"}, "cycles": 2, "env": {"USERPROFILE": "..."}}
python tgs-viz/tools/run_task.py --list-json [--selftest]
python tgs-viz/tools/run_task.py --validate <task_id> --inputs-json JSON      prints {"ok": bool, "errors": {...}}
python tgs-viz/tools/run_task.py --lock-status
        prints {"locks": {"<name>": {...holder, "alive": bool}}, "active": [{...entry, "alive": bool, "status": "..."}]}
python tgs-viz/tools/run_task.py --reap
        applies the stale rule (7.6) to every active entry; prints {"reaped": [{"job_id", "status"}]}
python tgs-viz/tools/run_task.py --kill <job_id>
        for a runner that does not answer a kill stop (8.8): checks the runner's identity (7.6), runs
        taskkill /PID <runner pid> /T /F, resets OOTP input when the running step drives OOTP, writes
        state killed, releases the job's locks, removes its active entry; prints {"ok": bool, "status": "..."}
```

`--launch`: `subprocess.Popen([sys.executable, run_task.py, "--job", job_dir], stdin=DEVNULL, stdout=<runner.log>, stderr=STDOUT, close_fds=True, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB)`. On `OSError` (a job object that forbids breakaway answers access denied), retry once without `CREATE_BREAKAWAY_FROM_JOB`. The runner inherits the environment, secrets included; the launcher keeps nothing and exits. Why: libuv does not set `CREATE_BREAKAWAY_FROM_JOB` for detached children, so whether a job outlives the Launch window would otherwise depend on the window host (user setup review, item 9). The flag has no effect when the launcher is in no job.

`--plan` output:
```json
{"task": "get_ratings", "mode": "console",
 "items": [
   {"type": "echo", "lines": ["..."]},
   {"type": "pause"},
   {"type": "prompt", "input": "sessionid", "text": "Paste your sessionid value, then press Enter:"},
   {"type": "command", "step_id": "tgs_ratings", "argv": ["python", "tgs-viz\\ingest\\refresh.py", "..."],
    "env": {"STATSPLUS_COOKIE": "sessionid=<sessionid>;csrftoken=<csrftoken>"}, "assumed_exit": 0},
   {"type": "confirm", "step_id": "sync_tgs", "question": "..."}
 ],
 "fails": ["TGS-draft"], "exit_code": 0, "status": "partial"}
```
`env` lists only `STATSPLUS_COOKIE` (value with symbolic placeholders, or `null` = unset). The equivalence test compares this list. The plan leaves out locks, the archive check, `excel_check` and the countdown: they print nothing when nothing else runs and the archive exists.

### 6.2 Named preludes and handlers (A codes them; the registry names them)

`cookie_pair(L1, L2)` (Get StatsPlus Ratings.bat:20-64):
1. Run both probes. `tok_L` = exit 0.
2. Both: echo :42, cookie = unset (explicitly cleared).
3. Neither: echo :33-35; prompt `Paste your sessionid value, then press Enter:`; prompt `Paste your csrftoken value, then press Enter:`; cookie = `sessionid=<sid>;csrftoken=<csrf>` (blank parts allowed; refresh.py:269-271 treats blanks as no cookie).
4. One: HAVE/NOTOK/NOSLUG echo :53-57; prompt `Paste your sessionid value (Enter = skip <NOTOK>): `; blank: cookie unset; else prompt `Paste your csrftoken value, then press Enter: ` and set cookie.
Job mode: no prompts; uses the `sessionid`/`csrftoken` secrets with the same rules (blank = Enter). A non-blank secret must have at least 8 characters (8.5), so log masking never has to mask a short string.

`cookie_single(L)` (Get StatsPlus History.bat:43-63): probe; token: echo :49-50, cookie unset; no token: echo :53-60, both prompts, cookie set. Scope is set by the task (History: the history step only, then cleared as :71-73).

`history_codes`: section 4.3 get_history. It compares the exit code as cmd's signed 32-bit value, as `set "HX=%errorlevel%"` did, so 3221225786 (Ctrl+C) is "any other nonzero": FAILS gets `<LG>-history` and the archive steps run, as today.

`stopafter` (Grind): nonzero exit prints the bat's two-line message, sets flag `stopafter`, continues the cycle; at cycle end the finish is "stopped" with exit 1.

`gate`: console runs `pause` through `subprocess.call("pause", shell=True)` so the text and key behavior match cmd. Job mode: a gate with no precondition is skipped (the Start click is the confirmation); a gate with a precondition is the required `ootp_ready` confirm input; `paste_reminder` and `selftest.gate` are mid-run prompts (7.4).

### 6.3 Job-mode substitutions

| Console (bat) | Job mode |
|---|---|
| `sync_datapoints.py ... --write` that would ask y/N (sync_datapoints.py:376) | preview without `--write`, sum `count_regex`; 0: log "Nothing to apply." and skip; else prompt; yes: apply with `--write --yes`; no: log "Skipped (not applied)." |
| `cleanup_clones.py ... --junk` that would ask y/N (cleanup_clones.py:110) | preview with `--dry-run`; regex `will DELETE (\d+) clone league`; the prompt shows the preview lines (every folder name); yes: apply with `--yes` |
| `pause` before start | nothing, or the required confirm input |
| `pause` mid-run (Recalibrate BLM.bat:41) | prompt kind `gate` |
| `set /p` | inputs collected before start |
| nothing (the bats never checked) | `excel_check` gate before each sheet write (7.3) |
| nothing | 5-second "Hands off" countdown before the first OOTP-driving step (7.3) |
| an echo line that names a console key ("press a key", "answer N", "Ctrl+C") | the same line with the page's button (Continue, Keep, Stop after this cycle, Kill now). The registry holds such a line as `{"console": ..., "job": ...}`; the console text stays byte-equal to the bat |

Every job-mode child gets `stdin=subprocess.DEVNULL`, so a missed `input()` hits EOF. D's EOF guards (11.15, 11.19, 11.20) turn that into "no".

### 6.4 Exit codes, step verdicts and Ctrl+C

Console mode returns the old bat's exit code, computed with cmd semantics: `exit /b N` sets N; otherwise the errorlevel of the last external command run (a probe counts). `echo`, `set`, `if`, `goto`, `pause` do not change it in a `.bat` file. Examples: Bank Dev Seasons success 0, failure 1; Get StatsPlus Ratings = pull_report's code; Update Dispersal Board on failure = draft.py's code.

Step verdict, both modes: any nonzero `Popen.returncode` is a failure for the step's `on_error`. That includes codes of 0x80000000 and up, which cmd reads as negative numbers: Ctrl+C ends a Python step with 0xC000013A (3221225786), and a crash ends it with codes like 0xC0000005. In the old bats `if errorlevel 1` is false for a negative errorlevel, so such a step counted as a success. This is the one deliberate change in how a step is judged (allowed difference 2 in 14.1). `history_codes` keeps the signed compare (6.2), which already treated it as a failure.

Extra console codes from run_task itself: 2 = unknown task, bad settings, bad input, or the archive check (7.3); 3 = refused by a lock, or C at the data-lock question (7.5); 130 = stopped by Ctrl+C. Lock refusal text: `  <title> is running and <reason>. Wait for it to finish, or stop it on the app's Control page.` Reasons: `ootp` "uses OOTP and your mouse"; `clones.<L>` "uses the <L> clone saves"; `dumps.<ID>` "uses the <ID> dump folder"; `task.<id>` "is this same task".

Job mode exit codes are informational (the server reads state.json): 0 done/partial/stopped, 1 failed, 2 invalid, 3 refused, 4 killed.

Ctrl+C in console mode:
- Steps run with no creation flags and the console's own stdin, stdout and stderr (7.3), so a Ctrl+C reaches the step and run_task together, as in the bat. run_task also treats Ctrl+Break (SIGBREAK) the same way, so a test can send `CTRL_BREAK_EVENT` to a process group.
- At the start gate or the data-lock question: print `  Cancelled. Nothing ran.` and exit 130.
- During a step: wait for the step to end (it got the Ctrl+C too), then ask `  Stop the whole run? (Y/N) `. Y, a blank line, EOF or a second Ctrl+C: the step is `stopped`, the rest `skipped`, status `stopped`, locks released, exit 130. N: judge the step's exit code under its own `on_error` (a Ctrl+C code is a failure, see above) and carry on. In the bat, N at cmd's "Terminate batch job (Y/N)?" also carried on.
- cmd saw the Ctrl+C too, so after run_task returns it may print its own "Terminate batch job (Y/N)?". Either answer only ends the wrapper; Y skips the final pause.

### 6.5 Console output and wrappers

Console mode prints the banner and echo lines from the legacy bat, at the same points, as cmd prints them: `tasks.py` stores each line after cmd's caret rules, so `-^>` is stored as `->`, `^(code 2^)` as `(code 2)` and `^-^>` as `->` (14.1 checks golden lines). `tasks.py` holds that text itself; the `legacy_bats` copies are test fixtures only and are never read at run time. Allowed text changes (and only these):
1. "Reload the webapp", "Reload the web app", "refresh your browser", "Refresh the app (F5)" become "The open app updates itself; no reload needed." (Live refresh makes them stale.)
2. Get StatsPlus History.bat:114 "Run StatsPlus Tokens.txt, or run this again..." becomes "Paste the league's token into StatsPlus Tokens.txt, or run this again and paste sessionid and csrftoken."
3. Get StatsPlus History.bat:127-128 "run Set StatsPlus Tokens.bat" becomes "paste it into StatsPlus Tokens.txt".
4. Bank Season.bat:20-23 becomes "  Mid-season, the actuals step skips that league. The projection snapshot still runs." (the real behavior, fetch_actuals.py:112-118).
5. Get StatsPlus History.bat:18-22 runtime text becomes "How long: StatsPlus decides. Each snapshot waits only when StatsPlus says it is too soon. The first run can take up to about 2 hours."
6. bank_dev adds one reminder line per extra league just before its Done block (4.3).

New lines that print only when another task holds a lock (7.5), the archive is missing (7.3) or the user presses Ctrl+C (6.4) are not text changes: they never print on a plain run.

The equivalence test prints a text diff report so a reviewer can see every changed line.

Wrapper template (CRLF, ASCII; `<title>` = the legacy bat's `title` line if it had one; `<cd>` = the legacy `cd` line):
```bat
@echo off
title <title>
<cd>
set "TGS_PY=python"
python -c "" >nul 2>nul && goto tgs_run
set "TGS_PY=py -3"
py -3 -c "" >nul 2>nul && goto tgs_run
echo.
echo   Python is not installed, or it is not on PATH.
echo   Install Python 3.13 from python.org and tick "Add python.exe to PATH".
echo   Then start this again.
pause
exit /b 9009
:tgs_run
%TGS_PY% "tgs-viz\tools\run_task.py" <task_id> %*
set "RC=%errorlevel%"
pause
exit /b %RC%
```
Root bats use `cd /d "%~dp0"`. ootp bats use `cd /d "%~dp0.."`. Bats without a title line (Get StatsPlus Ratings, Get StatsPlus History, Update Regular Game) get none. The wrapper calls `python` when it runs, as every bat does today, and falls back to `py -3` (a python.org install without "Add to PATH" has only `py`). Any Python 3.11+ can run run_task.py; the steps use the settings interpreters. On the user's PC `python -c ""` succeeds, so the call is the same `python` as before. With only the Microsoft Store alias, `python` exits 9009 quietly here and the wrapper prints the install line instead of the Store message.

`Check Setup.bat`: same template with task `doctor`, title `TGS - Setup check`.

### 6.6 Launch TGS.bat (new content)

```bat
@echo off
title TGS Projections
cd /d "%~dp0tgs-viz"

echo ========================================
echo   TGS Projections - Starting...
echo ========================================
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo   Node.js is not installed, or it is not on PATH.
  echo   Install Node.js 22 LTS from nodejs.org, then start this again.
  pause
  exit /b 1
)

if not exist "node_modules\.bin\vite.cmd" (
  echo   The app's packages are not installed yet.
  echo   Open a terminal in the tgs-viz folder and run:  npm install
  echo   Then start this again.
  pause
  exit /b 1
)

:: Start the dev server (opens browser automatically)
call npx vite --port 3000 --strictPort --open
if errorlevel 1 (
  echo.
  echo   The app stopped. If the message above says port 3000 is in use,
  echo   the app may already be running: use its browser tab, or close the
  echo   other TGS Projections window first.
  echo   If no other TGS window is open, another program is using port 3000. Close it.
  pause
)
```
Why `--strictPort`: without it a second launch silently moves to 3001 (strictPort defaults to false, config.js:25695), and the page opens with none of the saved localStorage state, including the saved league (critic item 2). With it, a foreign program on port 3000 also stops the app, which is why the last message line exists.

### 6.7 Old bats, kept for one release

`old bats (backup)/` holds the 13 root legacy bats and `old bats (backup)/ootp/` the 5 ootp ones, as they were at `ef23800`, with CRLF line endings and one change each: the root ones' `cd /d "%~dp0"` becomes `cd /d "%~dp0.."`, and the ootp ones' `cd /d "%~dp0.."` becomes `cd /d "%~dp0..\.."`. They take no locks and know nothing about the Control page. They exist for one reason: if run_task breaks after the merge, the user double-clicks the same name in this folder and gets today's behavior. The integrator adds a STATUS.md line to delete the folder one release later. A's equivalence test checks each copy against its legacy fixture: equal except that one line and the line endings.

---

## 7. Jobs, locks and file formats (A writes, B reads)

### 7.1 Layout

```
<control>/active/<job_id>.json            run_task: one entry per running or queued job (7.2); removed at the end
<control>/locks/<name>.json               run_task: one file per held lock (7.5)
<control>/jobs/<job_id>/request.json      B writes (job mode) or run_task writes (console mode)
<control>/jobs/<job_id>/state.json        run_task only, atomic
<control>/jobs/<job_id>/events.jsonl      run_task only, append, one JSON object per line, flushed per line
<control>/jobs/<job_id>/log.txt           run_task only (job mode): merged child output plus run_task's echo lines
<control>/jobs/<job_id>/runner.log        stdout and stderr of the launcher and the runner (B opens it for the spawn)
<control>/jobs/<job_id>/heartbeat         empty file; mtime touched every 5 s by a run_task thread
<control>/jobs/<job_id>/prompt.json       run_task writes while waiting; deletes after the answer
<control>/jobs/<job_id>/answer.json       B writes (tmp then rename)
<control>/jobs/<job_id>/stop.json         B writes
<control>/jobs/<job_id>/new_league_spec.json, precheck.json   new_league task only
<control>/tmp/                            short-lived files for B's validate and settings calls
<control>/rollback/<job_id>/              New League rollback (folders moved here, never deleted)
<control>/removed/<ID>-<stamp>/           remove_league (folders moved here, never deleted)
```

`job_id` = `YYYYMMDD-HHMMSS-<task_id>-<4 hex>`, which always matches `^\d{8}-\d{6}-[A-Za-z0-9_.-]+-[0-9a-f]{4}$` (B checks every `:id` against it, 8.5). Console mode creates its folder too (no log.txt; output goes to the console). run_task keeps the newest 50 finished job folders and deletes older finished ones at start, never one with an active entry, and never a lost or failed New League job whose league is still `pending` in settings.local.json (its clean-up needs the spec and precheck files, 12.6).

Only run_task writes state.json, events.jsonl, lock files and active entries. B writes only request.json, answer.json, stop.json and files under `tmp/`.

### 7.2 Formats

`request.json`: `{"schema": 1, "task": "get_ratings", "inputs": {...non-secret...}, "secret_names": ["SESSIONID"], "mode": "job", "requested_at": "ISO", "by": "control-page" | "console"}`

Active entry `active/<job_id>.json`: `{"schema": 1, "job_id": "...", "task": "...", "title": "...", "mode": "job" | "console", "pid": 1234, "pid_started": 133720000000000000, "started": "ISO"}`. Written first thing, before settings load (7.3).

Lock file `locks/<name>.json`: `{"schema": 1, "name": "data", "job_id": "...", "task": "...", "title": "...", "mode": "...", "pid": 1234, "pid_started": 133720000000000000, "since": "ISO"}`.

`state.json`:
```json
{"schema": 1, "id": "...", "task": "...", "title": "...", "mode": "job", "status": "running",
 "pid": 1234, "pid_started": 133720000000000000, "started": "ISO", "ended": null,
 "inputs": {"league": "TGS"}, "secrets_given": ["sessionid"],
 "steps": [{"index": 0, "id": "tok_tgs", "title": "...", "status": "ok", "exit": 0,
            "started": "ISO", "ended": "ISO", "tag": null, "writes_app_data": false}],
 "current": 3, "cycle": null, "fails": [], "prompt": null, "stop": null,
 "locks_held": ["task.get_ratings", "data"], "data_lock": "held",
 "waiting_for": null, "pending_leagues": ["BLM"],
 "message": null, "fix_task": null,
 "summary": ["Steps that did not update: TGS-draft"], "exit_code": null}
```
- `data_lock`: `null` (not needed yet, or released), `"waiting"`, `"held"`, `"skipped"` (console "run anyway").
- `waiting_for`: `{"job_id", "title", "lock"}` while the job waits for a lock, else null.
- `pending_leagues`: the fileMap leagues (`"*"` = league null, 9.2) that steps still to come will write: in this run, or in this cycle for an endless task. Built from each step's `app_leagues`. Updated at job start, at each step end and at each cycle start. A step whose `when` is already known false is left out; any other step still to come counts. Any stop, a `history_codes` stop or the job end empties it. B holds a league's player files until the league leaves this list (9.3).
- `message`, `fix_task`: a plain line and a task id for `invalid` and `failed` ends, for example the archive check (7.3).

Statuses: `starting`, `queued` (waiting for the data lock before its first step), `running`, `waiting` (prompt open), `done`, `partial`, `failed`, `stopped`, `killed`, `invalid`, `refused`, `lost`. Step statuses: `pending`, `running`, `ok`, `failed` (fail or collect), `ignored_fail`, `skipped`, `killed`, `stopped`.

`events.jsonl` (every line has `seq` from 1 and `at`):
`job_start {task, mode, steps_total}`, `step_start {index, step_id, title, argv}`, `step_end {index, step_id, status, exit, seconds, tag, writes_app_data}`, `cycle_start {cycle}`, `league_done {league}` (a league left `pending_leagues`), `lock {name, action: "taken" | "released" | "waiting" | "skipped"}`, `prompt {prompt_id, kind, text, details, choices}`, `answer {prompt_id, value}`, `stop_requested {mode}`, `message {level: "info" | "warn" | "countdown", text}`, `job_end {status, exit_code, fails, summary}`.

`prompt.json`: `{"prompt_id": "p3", "kind": "confirm" | "gate", "step_id": "...", "title": "...", "text": "...", "details": ["last 40 preview lines"], "choices": [{"id": "yes", "label": "Apply"}, {"id": "no", "label": "Skip"}], "default": "no", "created": "ISO"}`

`answer.json`: `{"prompt_id": "p3", "value": "yes"}`. A value not in `choices` is ignored (logged).

`stop.json`: `{"mode": "after_step" | "after_cycle" | "kill", "requested_at": "ISO"}`. On a `queued` job any mode ends it `stopped` before anything runs.

### 7.3 Runtime rules

Start, both modes, in this order (with `TGS_DRY_RUN=1`, console mode prints the plan and exits 0 before step 1: no job folder, no active entry, no lock, no question):
1. Write state `starting` and the active entry. This happens before settings load. A top-level `try/finally` makes sure a run that dies early still ends with a final state: any exception becomes state `failed` with the exception's last line as `message` (the traceback goes to runner.log or the console), locks are released and the active entry removed.
2. Load settings and the task. A problem gives `invalid` (exit 2) with the plain message.
3. Archive check, when `needs_archive`: if `tgs-viz/backtest/ratings_history.db` is missing and any `tgs-viz/backtest/vintages/*/_pulls.csv` exists, the job ends `invalid` with `message` "The ratings archive is missing. Rebuild it first: Control, Setup check, Rebuild ratings archive." and `fix_task` `restore_ratings_db`. Console prints the message plus "Or run: python tgs-viz\backtest\vintage_backup.py --restore" and exits 2. The database path follows `RATINGS_ARCHIVE_ROOT` as ratings_db does; `RATINGS_DB_ALLOW_NEW=1` (worktree tests only) skips the check. Why: on a fresh clone the archive is gitignored, `ratings_db.connect()` would create an empty one (ratings_db.py:152-153), `ratings_db.py --export` would then write `"players": {}` over the shipped rating_trends.json (ratings_db.py:1259, :1282), and `vintage_backup.py --restore` refuses once a database exists (vintage_backup.py:111-113). D adds the same guard inside `connect()` (11.22).
4. Console: banner, then the start gate (pause) if the task has one.
5. Take the whole-run locks (7.5). A conflict gives `refused` (console message, exit 3).
6. If the first step needs the data lock and it is busy: job mode waits as `queued`; console asks (7.5).
7. Run the steps.

Child processes:
- Job mode: `subprocess.Popen(argv, cwd=REPO, stdin=DEVNULL, stdout=PIPE, stderr=STDOUT, env=..., creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP)`. CREATE_NO_WINDOW matters: the runner has no console, and without the flag every child would open a visible console window.
- Console mode: no creation flags at all, and stdin, stdout and stderr inherited. A child in a new process group would ignore Ctrl+C, and run_task would wait forever. Console mode still polls `stop.json` every 0.5 s during a step and between steps.
- Every step gets `TGS_JOB_ID` in its env.

Log masking (job mode):
- The values to mask are the non-blank secret values of this job, as UTF-8 bytes. Validation (8.5) makes each one at least 8 characters, so an empty or tiny value never reaches `bytes.replace`.
- The reader thread keeps a carry of the last (longest secret length minus 1) bytes of each chunk and joins it to the front of the next chunk before masking, so a secret split across two pipe reads is still masked. The carry is masked and written on the 300 ms idle flush, at child exit and at job end.
- The same masking applies to run_task's own echo lines, to prompt details and to `message` texts.

Secrets: read `TGS_SECRET_*` at start, match each name to the task's declared secret inputs without regard to case, drop unknown names (a warning without the value), delete them from `os.environ`, pass them only into the env of steps that reference them. Never write them to request.json, state.json, events, prompts or the log.

Heartbeat: a thread touches `heartbeat` every 5 s. B shows "not responding" when it is older than 60 s. The heartbeat never decides that a job is dead (7.6).

Stops: `after_step` finishes the running step, marks the rest `skipped`, status `stopped`. `after_cycle` (endless tasks) finishes the cycle including recalibrate and cleanup, then stops. `kill`: `taskkill /PID <child> /T /F` (CREATE_NO_WINDOW); when the killed step has `drives_ootp` or runs `ootp\winsim.py`, run_task then runs `@py ootp\winsim.py --reset-input` (15 s timeout, result logged), so Alt or the mouse button is never left held down (winsim.py:263); the step is `killed`, the rest `skipped`, status `killed`. A stop while a prompt is open answers it with the safe choice (`no` / `Stop`) and then applies the mode. A task with `rollback` runs it after a stop or kill (12.3). Console mode honors `stop.json` the same way and prints `  Stopped from the app's Control page.`

"Hands off" countdown (job mode only): before the first step in the run with `drives_ootp: true`, run_task writes `message {level: "countdown", text: "Hands off: OOTP starts in N"}` for N = 5, 4, 3, 2, 1, one per second. A stop during the countdown ends the job `stopped` before the step starts. The bat's pause gate plays this part in console mode.

`excel_check` (job mode only; console mode skips it and prints nothing): for each name in `excel.files`, look for `~$<name>` in `excel.folder`. If one exists, open a prompt kind `gate`: text "Excel has <name> open in <folder>. Close Excel, then press Continue. If Excel is closed and this still shows, delete the file ~$<name> in that folder.", choices Continue / Stop. Continue checks again and asks again while the file is there. Stop ends the job `stopped`. In an endless task the cycle waits at this prompt, which is better than today: the sync write fails and the Grind stops.

### 7.4 Mid-run prompts

run_task writes `prompt.json`, appends a `prompt` event, sets state `waiting`, then polls for `answer.json` every 0.5 s with no timeout. On an answer it appends `answer`, deletes both files, sets state `running`.

### 7.5 Locks

Names: `task.<task_id>`, `ootp`, `clones.<LG>`, `dumps.<ID>`, `data`. File: `<control>/locks/<name>.json`. Which task takes which: 4.10. Read-only tasks take none.

Take: write the content to `<name>.json.<pid>.tmp`, then `os.rename(tmp, "<name>.json")`. On Windows `os.rename` raises `FileExistsError` when the target exists, so exactly one taker wins and a reader never sees an empty or half-written lock. On `FileExistsError`: read the holder; if the holder is gone by the rule in 7.6, reap its job and try once more; else the lock is busy. The tmp file is removed in every case. A lock file that opens but holds no JSON object and is older than 5 s was cut short by a crash or a power cut: it names no holder, so the taker deletes it and tries again. `--reap` removes such lock files too, and reaps an active entry in that state by its file name (unless its state.json names a live runner); `--kill` falls back the same way. Lock names must match `^[A-Za-z0-9_.-]+$` without `..`; `joblock.lock_path` refuses any other name.

Release: delete the lock file only when its `job_id` is this job's.

Whole-run locks are taken together right after the start gate (so a bat window that sits at "Press any key" blocks nothing), in name order. If any one is busy, release the ones already taken and refuse.

The data lock:
- A non-endless task takes it right before its first step with `data: True` and holds it to the end.
- An endless task takes it before the first `data: True` step of each cycle and releases it at the end of that cycle.
- Busy before the first step runs: job mode waits as `queued`. Console mode asks:
  ```
    <title> is updating app data right now (started HH:MM).
    W = wait for it, then run    R = run now anyway    C = cancel
    Type W, R or C, then press Enter (Enter = W):
  ```
  R runs without the lock (`data_lock: "skipped"`; the log says so once). C exits 3. EOF waits.
- Busy later (the first data step comes after an OOTP step, or a new Grind cycle starts its recalibrate): wait, printing `  Waiting for <title> to finish before <next step title>...` once. A stop request while waiting ends the job `stopped`. In an endless task the cycle's recalibrate then does not run; the next run's calibrate picks up the finished clones.

B's pre-check (8.5) reads the same files to answer 409 fast. run_task's take is the real one: if B's pre-check passed but the take loses a race, the job ends `refused`.

### 7.6 Process identity and stale jobs (one rule, one implementation)

`joblock.proc_start_time(pid)` (ctypes, no packages): `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)`; no handle gives None. `GetExitCodeProcess`; anything but `STILL_ACTIVE` (259) gives None. `GetProcessTimes` gives the creation time as a 64-bit FILETIME integer. The handle is always closed.

`joblock.alive(rec)` = `proc_start_time(rec["pid"]) == rec["pid_started"]`. A reused pid has another start time, so it reads as gone. Every pid that run_task records (active entry, lock files, state.json) is stored with its `pid_started`.

A job is stale when its active entry's runner is not alive by that rule. Nothing else makes a job stale: not an old heartbeat, not a missing state.

Reap (`run_task.py --reap`, and every lock take that finds a dead holder) handles each stale active entry: no state.json, or state `starting`: write state `failed`, message "The runner stopped before it started the task.", plus the last 20 lines of runner.log in `summary`. Any other non-final state: write `lost` with `ended`. Then release every lock whose `job_id` is that job's and remove the active entry. A lost New League job keeps its spec and precheck files for the cleanup task (12.6).

B and doctor never apply this rule themselves. B calls `--reap`, `--lock-status` and `--kill` (8.8). doctor imports `joblock` and only reports (13.1).

---

## 8. Vite plugin and HTTP API (B)

### 8.1 vite.config.js (exact)

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Data files under public/data are fetched, never imported: a write there must never reload the page.
const noPublicDataHmr = {
  name: 'tgs-public-data-no-hmr',
  apply: 'serve',
  hotUpdate: {
    order: 'post',
    handler({ file }) {
      if (/[\\/]public[\\/]data[\\/]/.test(file)) return []
    },
  },
}

// The Control panel. A dynamic import that esbuild cannot follow, so Vite does not bundle it into
// this config: a broken control file can never stop the app or the league data from loading.
async function loadControl() {
  try {
    const url = new URL('./control/plugin.js', import.meta.url).href
    const mod = await import(/* @vite-ignore */ url)
    return [mod.default()]
  } catch (e) {
    const reason = String((e && e.message) || e)
    console.warn(`[tgs-control] The Control panel is off: ${reason}`)
    return [{
      name: 'tgs-control-off',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use('/__tgs/ping', (req, res) => {
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ ok: false, api: 1, control: { on: false, reason } }))
        })
      },
    }]
  }
}

export default defineConfig(async () => ({
  plugins: [react(), tailwindcss(), noPublicDataHmr, ...(await loadControl())],
  cacheDir: process.env.TGS_VITE_CACHE_DIR || undefined,
  server: {
    port: 3000,
    open: true,
    watch: {
      ignored: [
        '**/backtest/**', '**/engine/**', '**/ingest/**', '**/tools/**', '**/tests/**',
        '**/__pycache__/**', '**/*.tmp',
        '**/public/data/**/*.bak-*', '**/public/data/**/*_engine.json',
        '**/public/data/**/*_scurve_preview.json', '**/public/data/**/*_export.json',
        '**/public/data/* - Copy/**',
      ],
    },
  },
}))
```
- Why the dynamic import: Vite bundles the config with esbuild and bundles every relative import into it (config.js:35801-35880, the `externalize-deps` filter skips paths that start with `.`). A static `import tgsControl from './control/plugin.js'` would make any syntax error in a control file, or any throw while it loads, stop Vite before it serves one file. esbuild leaves `import(url)` with a non-literal argument alone, so Node loads it at run time inside the `try`. Side effect: control files are no longer config dependencies (rule 1.9), and Node caches the module for the life of the process, so a control file edit takes effect at the next Launch.
- `noPublicDataHmr` lives in the config, not in the plugin, so the no-reload rule holds even when Control is off. Returning `[]` empties the module list (config.js:26011-26014) and lands in the "no modules matched" branch, which reloads only `.html` files (config.js:26047-26061).
- `cacheDir: undefined` keeps Vite's default (`config$2.cacheDir ? ... : pkgDir/node_modules/.vite`, config.js:35530), so the user's PC is unchanged. Test servers set `TGS_VITE_CACHE_DIR` (rule 1.5).
- Never ignore the live `public/data/**/*.json` files: Vite keeps its `publicFiles` set only from watcher add/unlink events (config.js:25558-25570), and a new league's `hitters.json` must enter that set or Vite answers with the SPA fallback (config.js:22419-22421). Nothing under `src/` imports from backtest, engine, ingest or tools (checked).

### 8.2 Plugin shape

```js
let current = null   // the live instance; module-level because Node keeps this module across Vite restarts

export default function tgsControl() {
  return {
    name: 'tgs-control',
    apply: 'serve',
    configureServer(server) {
      safe('configureServer', () => {
        if (current) current.dispose()        // the instance from before a restart
        const inst = createInstance(server)   // token, pollers, watcher and ws handlers, python probe
        current = inst
        server.middlewares.use('/__tgs', inst.handle)
        server.httpServer?.once('close', () => inst.dispose())
      }, (err) => turnOff(server, err))
    },
  }
}
```
- Mount with `server.middlewares.use('/__tgs', handler)` inside `configureServer` itself. That runs before Vite's SPA fallback (config.js:25603 vs :25620).
- `dispose()` clears every interval and timeout the instance made, removes the watcher and ws listeners it added, ends its open SSE responses, and kills nothing. A Vite restart closes the old server (its `httpServer` emits `close`) and loads the config again, which calls the plugin factory again. Without `dispose()`, two instances would poll the same jobs and both call `--reap` and `--kill`.
- `turnOff(server, err)`: mounts a ping-only middleware that answers `{ok: false, api: 1, control: {on: false, reason}}`, logs one line, and touches nothing else.
- On every `configureServer` (including a restart): new token, read `<control>/active/`, re-adopt every active job (tail from current file sizes), probe `python.main` (8.5), refresh the catalog in the background. Jobs survive Vite restarts and the Launch window closing (decision 3).
- The port is read per request from `req.socket.localPort`, never at start: `server.httpServer.address()` is null inside `configureServer`, before the server listens.

### 8.3 Guards (every `/__tgs/` request)

1. `req.socket.remoteAddress` in `127.0.0.1`, `::1`, `::ffff:127.0.0.1`. Else 403.
2. `Host` header equals `localhost:<port>`, `127.0.0.1:<port>` or `[::1]:<port>`, where `<port>` = `req.socket.localPort` (the port this request arrived on; never the literal 3000). Else 403.
3. If `Origin` is present it must equal `http://` + one of those hosts. If absent, `Sec-Fetch-Site` (when present) must be `same-origin`. Else 403.
4. Token: header `X-TGS-Token` (or query `t` for the SSE GET) equals the per-start token. Else 401. `GET /__tgs/ping` is the only route without a token.
5. POST: `Content-Type` starts with `application/json`; body at most 64 KB; valid JSON. Else 400 / 413 / 415.
6. Every `:id` matches `^\d{8}-\d{6}-[A-Za-z0-9_.-]+-[0-9a-f]{4}$`, and `path.dirname(path.resolve(jobsDir, id))` equals `jobsDir`. Else 404 `no_job`.

Errors are JSON: `{"error": {"code": "busy", "message": "plain words", ...}}`.

### 8.4 Token handshake

- `configureServer`: `token = crypto.randomBytes(24).toString('hex')`.
- `server.ws.on('tgs:hello', (data, client) => client.send('tgs:token', { token, port: server.httpServer?.address()?.port ?? null, api: 1 }))`. The hello always arrives after the server listens.
- Client: `import.meta.hot.send('tgs:hello', {})` and `import.meta.hot.on('tgs:token', ...)`. Vite's own websocket already requires Vite's token for any request with an Origin (config.js:20352), so only pages Vite served can ask. The token lives in page memory only (never localStorage).

### 8.5 HTTP API

| Method | Path | Request | Success | Errors |
|---|---|---|---|---|
| GET | `/__tgs/ping` | none | `{ok: true, api: 1, control: {on: true}, python: {ok, argv, version, code, message}, live_refresh: bool}`; with `TGS_SELFTEST=1` also `debug: {instances_alive, timers}`. `?probe=1` (token needed) runs the Python probe again first | 403, 401 |
| GET | `/__tgs/catalog` | `?refresh=1` | catalog (3.4) | 401; 503 `python_failed` `{message, stderr_tail}` |
| GET | `/__tgs/config` | none | `catalog.app_config` | 401, 503 |
| GET | `/__tgs/jobs/active` | none | `{jobs: [state, ...]}`: every job with an active entry (running, queued, waiting), oldest first | 401 |
| GET | `/__tgs/jobs` | `?limit=20` (1 to 100) | `{jobs: [state, ...]}` newest first. A folder with request.json, no state.json and no active entry, whose launcher has exited or which is older than 60 s, shows as `{id, task, status: "did_not_start", message}` (derived; B writes nothing) | 401 |
| GET | `/__tgs/jobs/:id` | none | `{job: state}` | 404 `no_job` |
| POST | `/__tgs/jobs` | `{task, inputs, secrets}` | 201 `{job}` once status is `running`, `waiting` or `queued`; 202 `{job: {id, status: "starting"}}` after 10 s | 400 `invalid_input` `{errors, message, fix_task}`, 400 `secret_in_inputs`, 400 `bad_secret` `{field}`, 404 `unknown_task`, 409 `conflict` `{job, lock}`, 409 `queue_full` `{job}`, 500 `python_failed` `{message}`, 500 `runner_failed` `{message, log_tail}` |
| GET | `/__tgs/jobs/:id/events` | `?t=<token>&from=<cursor>&tail=<bytes>` | SSE (8.6) | 404 |
| GET | `/__tgs/jobs/:id/log` | `?from=<offset>&max=<bytes, default 262144>` | `text/plain`, header `X-TGS-Next-Offset` | 404 |
| POST | `/__tgs/jobs/:id/answer` | `{prompt_id, value}` | `{ok: true}` | 409 `no_prompt` / `prompt_mismatch`, 400 `bad_value` |
| POST | `/__tgs/jobs/:id/stop` | `{mode}` | 202 `{ok: true}` | 409 `not_running`, 400 `bad_mode` (`after_cycle` on a task without it) |
| GET | `/__tgs/doctor` | none | doctor JSON (13.2) | 503 `python_failed`, 504 `timeout` (60 s) |
| GET | `/__tgs/settings` | none | `{merged, local, paths: {defaults, local}}` (from `settings.py --json` plus the raw local file) | 401, 503 |
| POST | `/__tgs/settings` | `{patch}` | `{ok: true, merged}` | 403 `key_not_allowed`, 409 `busy` (a job is active), 400 `invalid` `{errors}`, 400 `bad_interpreter` `{argv, output}` |
| POST | `/__tgs/settings/reset-local` | `{}` | `{ok: true, renamed_to}` | 404 `no_local_file`, 409 `busy` |
| GET | `/__tgs/new-league/options` | `?type=&version=` | output of `new_league.py options --json` | 400 `bad_query` |
| POST | `/__tgs/new-league/validate` | `{type, fields}` (never a token) | output of `new_league.py check --json` | 400 |

`POST /__tgs/jobs` flow:
1. Look the task up in the cached catalog, hidden tasks included (404 if missing; `selftest.*` only with `TGS_SELFTEST=1`).
2. Inputs: reject any key in `inputs` whose catalog input type is `secret` (400 `secret_in_inputs`). Non-secret values must be strings, numbers or booleans under 4 KB.
3. Secrets: every key must name a `secret` input this task declares (compared without regard to case); every value a string of at most 4096 UTF-8 bytes with no NUL, CR or LF; a value that is not blank after trimming must have at least 8 characters. Else 400 `bad_secret` naming the field, never the value.
4. Lock pre-check, from the files run_task writes (7.5): for each name in the task's `locks`, if `locks/<name>.json` exists and its holder's pid answers `process.kill(pid, 0)`, answer 409 `conflict` with that job and the lock name. If the task needs the data lock (any step has `data: true`) and any active job is `queued`, answer 409 `queue_full` (one waiting task at a time). A busy data lock is not a refusal: the new job starts and waits as `queued`.
5. Create `<control>/jobs/<job_id>/` and write `request.json` (no secrets; secret names upper-cased).
6. Spawn the launcher (8.7).
7. Poll `state.json` every 100 ms for up to 10 s: `running`, `waiting` or `queued` gives 201; `invalid` 400 (with `message` and `fix_task`); `refused` 409 `conflict`; `failed` 500 `runner_failed`. If the launcher exits nonzero, or emits `error`, and no state exists: call `run_task.py --reap` once (when Python starts at all) and answer 500 `runner_failed` with the last 20 lines of runner.log. Still `starting` after 10 s: 202.

Settings patch whitelist: `python.main`, `python.ml`, `node`, `ootp.installs.<ver>.saved_games`, `leagues.<id>.enabled`, `leagues.<id>.name`, `leagues.<id>.my_team`, `leagues.<id>.my_org`, `leagues.<id>.ootp_save`, `leagues.<id>.ootp_version`, `leagues.TGS.dispersal_orgs`. Interpreter probe: before saving `python.main`, `python.ml` or `node`, B runs the new argv once (no shell, 15 s timeout): Python with `-c "import sys; print(sys.version_info[0], sys.version_info[1])"`, which must print `3` and a minor of at least 11; Node with `--version`, which must be at least 20.19 (or 22.12 on the 22 line). A failure answers 400 `bad_interpreter` with the argv and the output tail, and nothing is saved. B writes the patch to `<control>/tmp/<random>.json` and runs `settings.py set --patch-file <file>` with the NEW `python.main` when the patch changes it (the old value may be the broken one), else with the current one. Then it deletes the file, probes Python again and broadcasts `tgs:catalog` and `tgs:control`.

`POST /__tgs/settings/reset-local` runs in Node only (no Python, so it works when Python is broken): it renames the local settings file (`settings.local.json`, or `TGS_SETTINGS_LOCAL`) to `settings.local.bad-YYYYMMDD-HHMMSS.json` in the same folder, then rebuilds the catalog, probes Python and broadcasts. 409 `busy` while any job is active.

`GET /__tgs/new-league/options`: `type` must be one of `statsplus`, `local_export`, `dev`, `clone`; `version`, when given, must match `^\d{2}$`. Else 400 `bad_query`. Both go into argv only after that check.

Python probe (for `ping`): at start, after each settings change and on `ping?probe=1` (the Setup page's Check again), B runs `python.main -c "import sys; print(sys.version)"`. Result: `{ok: true, argv, version}`, or `{ok: false, argv, code, message}` where `code` is `ENOENT` (the command does not exist), `9009` (only the Microsoft Store alias answered) or the exit code. The Setup page uses this to say "Install Python 3.13 from python.org and tick Add python.exe to PATH" without needing Python.

Short-lived Python calls (catalog, config, doctor, settings, options, validate, `--reap`, `--lock-status`, `--kill`) run with `execFile`-style spawn (no shell), `windowsHide: true`, cwd = repo root, timeout 60 s, an `error` listener, and a `.catch` on their promise. ENOENT and 9009 answer 503 `python_failed` with the plain probe message. They may run while a job runs.

### 8.6 SSE stream

Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `Connection: keep-alive`. First line `retry: 2000`.
- `event: hello` data `{job_id, cursor}`.
- `event: log` data `{text, offset, partial}`; `text` holds whole lines (`\r\n` and lone `\r` become `\n`); a held partial line is sent after 500 ms idle with `partial: true`. Decode UTF-8 safely across chunk edges.
- `event: step` data = a `step_start`, `step_end`, `cycle_start`, `league_done` or `lock` event.
- `event: message` data = a `message` event (the countdown uses it).
- `event: prompt` data = prompt; `event: state` data = state.json after any change; `event: done` data = `job_end`, then close.
- Console jobs have no log.txt: their stream carries step, message, state and done events only, and `GET .../log` answers 404 `no_log`.
- `: ping` comment every 15 s.
- Every event carries `id: e<seq>-l<offset>`. Resume from `Last-Event-ID` or `?from=`. `?tail=<bytes>` starts the log at `max(0, size - tail)` aligned to the next newline (default 262144).

### 8.7 Spawn

```js
const out = fs.openSync(path.join(jobDir, 'runner.log'), 'a');
let child;
try {
  child = spawn(py[0], [...py.slice(1), runTaskPath, '--launch', jobDir], {
    cwd: repoRoot, detached: true, windowsHide: true, stdio: ['ignore', out, out],
    env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8', ...secretEnv },
  });
} finally {
  fs.closeSync(out);
}
child.on('error', (err) => safe('launcher error', () => onLaunchFailed(jobId, err)));
child.on('exit', (code) => safe('launcher exit', () => onLauncherExit(jobId, code)));
child.unref();
```
- `py` = `python.main` (3.2). `secretEnv` = `TGS_SECRET_<NAME>` per secret, the name upper-cased. Never `shell: true`. B keeps nothing else of the secrets after the spawn.
- The `error` listener is required: a missing exe (ENOENT) arrives as an asynchronous `error` event, and Node throws when an `error` event has no listener, which would stop the dev server.
- `--launch` starts the real runner and exits (6.1). Exit 0: B follows the runner through `active/` (8.8). Nonzero exit or `error` with no final state: step 7 of the POST flow, or, after the POST has answered, a `tgs:job` with status `failed` and the runner.log tail.
- Every other `spawn` and `execFile` in B gets an `error` listener too.

### 8.8 Following jobs, stale jobs and the kill fallback

- B reads `<control>/active/` every 1 s. For each active job it tails `events.jsonl` and `state.json` every 500 ms. One poller serves SSE, `tgs:job` and the data flush (9.3).
- Liveness, cheap check: `process.kill(pid, 0)` in a `try` (on Windows libuv answers signal 0 with `GetExitCodeProcess` and sends nothing). Not alive: run `run_task.py --reap` (at most once per 5 s). Alive but the heartbeat is older than 60 s: `stale: true` in `tgs:job`, and the page offers Kill now. A reused pid reads as alive here; that only delays the reap until `--lock-status` or the next run_task start applies the exact rule (7.6).
- Kill fallback: if a `kill` stop is not reflected in `state.json` within 15 s, B runs `run_task.py --kill <job_id>`, which checks the runner's identity before it kills anything.
- B never runs `taskkill`, and never writes `state.json`, lock files or active entries. A pid alone cannot prove which process it is.

### 8.9 ws events (server to client)

| Event | Payload | When |
|---|---|---|
| `tgs:token` | `{token, port, api}` | reply to `tgs:hello`, that client only |
| `tgs:data` | `{league: string or null, keys: string[], files: string[], at: number, reason: "watch" or "step_end" or "league_done" or "job_end"}` | 9.3 |
| `tgs:job` | `{id, task, title, mode, status, step: {index, total, title} or null, prompt: boolean, stop: string or null, stale: boolean, waiting_for: object or null, at}` | any state.json change of any active job, and its final state |
| `tgs:catalog` | `{at}` | catalog rebuilt (settings changed, a watched file changed, a job ended, refresh requested) |
| `tgs:control` | `{on, reason, python, live_refresh}` | Control turned on or off, the Python probe changed, live refresh switched itself off |

Client to server: `tgs:hello` `{}` only.

### 8.10 Failure isolation

The user's leagues must load even when every part of Control fails.
- `safe(where, fn, onError?)` (control/safe.js) runs `fn` in `try/catch`. On an error it logs one line, `[tgs-control] <where>: <message>`, at most once a minute for the same `where`, calls `onError` if given, and returns `undefined`. Every entry point uses it: `configureServer`, the middleware (which answers 500 `{"error": {"code": "internal"}}` for that request; Control stays on), watcher handlers, ws handlers, interval and timeout callbacks, child process events. Every promise ends in `.catch` to the same log.
- A failure inside `configureServer` turns Control off (`turnOff`, 8.2). A request that fails does not.
- The live-refresh watcher unhooks itself after 10 errors in one minute. `ping` then reports `live_refresh: false`, `tgs:control` tells the page, and the footer says "Live refresh is off. Press F5 after an update."
- Control files read JSON with `fs.readFileSync` and `JSON.parse` inside `try`, never with `import`. `paths.js` reads `settings.local.json` per call, never at import time.
- 15.2 step 9 proves it: Vite starts and serves `/data` and all four leagues with a broken `settings.local.json`, with no `.control` folder, with `python.main` set to a missing exe, with a `plugin.js` that throws while it loads (`TGS_CONTROL_TEST_THROW=import`, which is the same path as a missing or unparsable control file: the dynamic import rejects), and with a throw inside `configureServer` (`TGS_CONTROL_TEST_THROW=configure`).

---

## 9. Live refresh

### 9.1 Stop the reloads (B)

- `tgs-viz/src/index.css:1` becomes:
  ```css
  @import "tailwindcss" source(none);
  @source "../src";
  @source "../index.html";
  ```
  Today the bare import (index.css:1) makes Tailwind scan the whole Vite root, including about 1 GB of data JSON, and register each file as a dependency of index.css (critic, app.vite). index.html has no Tailwind classes, so nothing is lost.
- The `noPublicDataHmr` hook and `server.watch.ignored` (8.1).

### 9.2 File map (B: `control/fileMap.js`; C reacts to the keys)

Paths are relative to `tgs-viz/public/data/`. `<LG>` must match `^[A-Za-z0-9_-]{1,16}$` (so `BLM - Copy` never matches).

| Path | league | key |
|---|---|---|
| `leagues.json` | null | `leagues` |
| `dev_rating_odds.json` | null | `odds` |
| `<LG>/age_curve.json` | `<LG>`, but null when `<LG>` is `DEV` (ageCurve.js:18 makes DEV's curve every league's curve) | `age_curve` |
| `<LG>/rating_trends.json` | `<LG>` | `trends` |
| `<LG>/calibration.json` | `<LG>` | `calibration` |
| `<LG>/park_lineup_values.json` | `<LG>` | `series` |
| `<LG>/` one of: hitters, pitchers, hitters_park, pitchers_park, hitters_draft, pitchers_draft, hitters_draft_park, pitchers_draft_park, hitters_draft_all, pitchers_draft_all, hitters_draft_all_park, pitchers_draft_all_park, draft_picks, iafa, r5, parks, park_list, metadata, market_fit, dev_signals, dev_ml (`.json`) | `<LG>` | `players` |
| anything else (`.bak-*`, `.tmp`, `_engine`, `_export`, `_scurve_preview`, `hitters_fa`, `dev_odds.json`, root legacy files, `nul`) | ignored | |

In `pending_leagues` and `app_leagues`, league null is written `"*"`.

### 9.3 Hold and flush (B)

Watch with `server.watcher.on('add' | 'change' | 'unlink')`. Map each path; drop ignored ones. B knows each active job's `status` and `pending_leagues` from its state.json (8.8). A job "claims" league L while its status is `running` or `waiting` and its `pending_leagues` holds L.

An event for league L (`"*"` for null) and key K goes by the first rule that fits:
1. **Player files wait for the league's last step.** K is `players` and some job claims L: hold the event. When no job claims L any more (L left `pending_leagues`, a `league_done` event, or the job reached a final state), stat the held files once, wait while they still change (at most 5 s), and broadcast one `tgs:data` for L with `reason: "league_done"` (or `"job_end"`).
2. **Other keys wait for the step.** Some job claims L: hold the event until that job's next `step_end`, then stat once (wait while they still change, at most 5 s) and broadcast (`reason: "step_end"`).
3. **No job claims L:** per league, wait until 2 s pass with no new event, then stat every file twice 500 ms apart. If any size or mtime differs (or a file appears or vanishes), restart the wait. After 60 s of continuous change, send anyway (`reason: "watch"`). This also covers a step that writes nothing for L while another task's files change, and writes from the old bats or by hand.

A job that turns `lost`, `killed` or any final status releases its holds at once. `unlink` events are sent too; the client keeps its old data on a 404.

Why rule 1: draft, r5, dev_signals and dev_ml all map to `players`, and a pull writes them in several steps. Flushing at each step end would re-parse about 90 MB for TGS five times, and between `dev_signals` (Get StatsPlus Ratings.bat:110) and the ML score (:122) the app would drop the ML numbers, because it uses `dev_ml` only when it comes from the same pull as `dev_signals` (usePlayerData.js:239-253). Proj Potential, Starter % and Star % would flip to the cell method and back. With rule 1 the user sees one consistent update per league, as after F5 today.

`app_leagues` per writer (A puts these in the registry; B relies on them; a step left out only loses its hold and falls to rule 3):

| Step (with `--write` where the script needs it) | `app_leagues` |
|---|---|
| `refresh.py --league L`, `draft.py --league L`, `r5.py --league L`, `iafa.py --league L` | `[L]` |
| `agecurve_fit.py --league L` | `[L]`, but `["*"]` when L is DEV |
| `export_calibration.py --league L`, `dev_signals.py --league L`, `ml\score.py --league L`, `bank_market_fit.mjs L` | `[L]` |
| `ratings_db.py --export` with no `--league` | the ids of `ratings_db.LEAGUES` (today `["TGS", "BLM"]`) |
| `ratings_db.py --export --league L` | `[L]` |
| `dev_rating_odds.py` | `["*"]` |
| `dev_odds.py` | `[]` (dev_odds.json is not an app file, 9.2) |
| `parks.py --write` | `["TGS", "BLM"]` |
| `extract_data.py --manifest-only` | `["*"]` |
| `export_league.py --league L` | `[L, "*"]` |
| `new_league.py register`, `register-manifest`, `remove`, `rollback` for id L | `[L, "*"]` |
| `selftest_steps.py touch` / `corrupt` on file F | the league of F (9.2) |

### 9.4 Client (C)

`src/lib/dataVersion.js`:
- `import.meta.hot?.on('tgs:data', ...)`. Coalesce events within 250 ms per league.
- Store: `versions[league][key]` counters and `global[key]` for league-null events. `useDataVersion(league, key)` (built on `useSyncExternalStore`) returns `versions[league][key] + global[key]`.
- Changed files: the store also keeps, per league and key, the last 50 `{version, files}` entries. `changedFilesSince(league, key, version)` returns the set of file names changed after `version`, or `null` when the log no longer reaches back that far (the caller then refetches everything).
- On each event, before bumping: `trends` deletes `ratingTrends` cache for that league; `age_curve` clears the ageCurve Map (league null clears all); `odds` resets the Make-it odds promise; `players` and `series` clear `_recent` in usePlayerData.js:303-312.
- Import direction (no cycles, no React in pure libs): `ratingTrends.js` and `ageCurve.js` stay pure, because node scripts import `futureValue.js`, which imports `ageCurve.js` (futureValue.js:50). They only export `invalidateRatingTrends` / `invalidateAgeCurves`, and `dataVersion.js` imports those. `usePlayerData.js` and `MakeItOddsPage.jsx` import `dataVersion.js` and register their resets with `registerInvalidator(key, fn)`, which `dataVersion.js` exports.
- `import.meta.hot` is undefined in a build or preview: the store stays at 0 and nothing refreshes (matches Launch TGS.bat, which runs the dev server).
- Only the open league refreshes. An event for another league only clears that league's caches; switching to it runs the normal load.

`src/hooks/useSelectedById.js`:
```js
// rowsByKind: { hitter: rows, pitcher: rows } (a page with one list passes one kind)
export function useSelectedById(rowsByKind)
  -> { selected, kind, select(row, kind), clear() }
```
It stores `{id: row.ID, kind}`, never the row. `selected` = the row in `rowsByKind[kind]` with that `ID`, found again after every data change, so the open card always shows the current numbers. When the ID is gone from the list (a league switch), it clears itself and the card closes.

Code changes, file:line at `ef23800`:

| Site | Change |
|---|---|
| `src/lib/ratingTrends.js:10, 27-39` | Export `invalidateRatingTrends(league)` (delete `cache[lg]`) |
| `src/lib/ageCurve.js:11, 36-43` | Export `invalidateAgeCurves()` (clear the Map) |
| `src/pages/MakeItOddsPage.jsx:44-58, 160-163` | Add `resetOdds()` (set `oddsPromise = null`) and call `registerInvalidator('odds', resetOdds)` at module load; effect deps add `useDataVersion(null, 'odds')`; keep the old odds on a null result after a refresh |
| `src/hooks/usePlayerData.js:82-113` (`useLeagues`) | Deps add `useDataVersion(null, 'leagues')` and any `trends` bump (a trends-only league is listed only when its rating_trends.json exists, :98-101). On failure keep the previous list; use `FALLBACK_LEAGUES` (:105-109) only when there was no previous list |
| `src/hooks/usePlayerData.js:122-272` (`usePlayerData`) | Soft refresh, rules below |
| `src/hooks/usePlayerData.js:303-312` | Add `clearRecent()` (empty `_recent`) and call `registerInvalidator('players', clearRecent)` and `registerInvalidator('series', clearRecent)` at module load |
| `src/hooks/usePlayerData.js:320-353` (`useSeriesPlannerData`) | Deps add `useDataVersion(league, 'series')`. When the previous status was `ready`, do not set `loading` (:325); swap on success, keep the old state on failure |
| `src/hooks/usePlayerData.js:511-519` (`useMeasuredCurve`) | Deps add `useDataVersion(null, 'age_curve')` plus the current league's `age_curve`; keep the old curve on null after a refresh |
| `src/pages/CalibrationPage.jsx:156-168` | Deps add `useDataVersion(league, 'calibration')`; set `undefined` only on a league change |
| `src/pages/TrendsPage.jsx:968-974` | Deps add `useDataVersion(league, 'trends')`; `setTrends(undefined)` only on a league change |
| `src/components/PlayerDetail.jsx:187-191, 268-272` | Deps add the trends and age_curve versions of `player._appLeague` |
| `src/pages/HittersPage.jsx:9-12`, `src/pages/PitchersPage.jsx:9-12` | Replace the row state and "clear the selection when `players` changes" (:12) with `useSelectedById({hitter: players})` / `({pitcher: players})` |
| `src/pages/DraftBoardPage.jsx:9-10, 338-340` | `useSelectedById({hitter, pitcher})` with the page's two draft lists; `playerType` becomes the hook's `kind` |
| `src/pages/MockDraftPage.jsx:17, 336, 380-383` | Same; kind from `player._type === 'H'` |
| `src/pages/RosterOptimizerPage.jsx:34, 241, 656, 733, 769, 831-834` | Same, over the page's hitter and pitcher rows; `entry.player` is looked up by its `ID` |
| `src/pages/MarketValuePage.jsx:23, 83-86, 471-473` | Already re-resolves by ID (`selectedCurrent`); switch to the hook so all six pages share one rule |
| `src/pages/OrganizationPage.jsx:288` | Take a new `parkMode` prop (App.jsx:434 passes it) and call `usePlayerData(league, 'neutral', parkMode !== 'neutral')`, so the neutral app data is not loaded twice |
| `src/pages/OrganizationPage.jsx:299-301`, `src/pages/WaiverClaimPage.jsx:53-55` | Default org (10.1). Effect deps become `[orgs, myOrg]`; a ref records that the user picked an org, and after that the effect only fixes an org that left the list. `my_org` comes from the async config and may arrive after `orgs` |

Soft refresh in `usePlayerData` (deps become `[league, parkMode, wantPlayers, version]`, `version = useDataVersion(league, 'players')`):
1. A ref holds the last `league|parkMode|wantPlayers` and the raw inputs of the last good load: each list key's rows after the Name filter and the `_appLeague` stamp (:189-193) but before any dev enrichment, plus `metadata`, `marketBank`, the parsed `dev_signals` and the parsed `dev_ml`, plus the version they reflect. If `league|parkMode|wantPlayers` changed, run today's hard path (:143-266), unchanged except that fetches may run in parallel and the raw inputs are stored in the ref.
2. Version-only change: do not call `setLoading`, `setError`, `setLoadProgress` or the reset at :143-155. Set `refreshing = true`.
3. Work out what to fetch from `changedFilesSince(league, 'players', ref.version)` (`null` = everything): a list key K is fetched when the changed set holds K's file for the current park mode, or the neutral file a missing `_park` draft file falls back to (:177-180). `metadata.json`, `market_fit.json`, `dev_signals.json` and `dev_ml.json` map to their own inputs. A changed file the current view does not use (for example `hitters_park.json` on Neutral) fetches nothing. Nothing to fetch: record the version and stop.
4. Fetch that set in parallel with the hard path's per-key code. A key whose fetch fails (404, not JSON, parse error) keeps its previous raw value and goes into `failedKeys`.
5. Rebuild from the raw inputs with the hard path's own tail, moved into one function: dev signals onto the raw lists, then dev ML with the same-pull guard (:227-253). Never enrich rows that were already enriched.
6. One `setData`. Set `refreshing = false`, `refreshedAt = Date.now()`, `refreshFailed = failedKeys.length > 0`. Retry the failed keys once after 5 s.
7. Return `{ data, loading, error, loadProgress, refreshing, refreshedAt, refreshFailed }`.
8. The `cancelled` flag (:141, :255, :268) still guards a league switch mid-refresh.

`meta.hasSignals` and `meta.hasMl` mean "the file was fetched and parsed", not "it was applied". The same-pull guard choosing the cell method is a normal result (an F5 gives the same), never a reason to reject a refresh.

`src/lib/softMerge.js` holds the pure parts with node tests: `keysToFetch(changedFiles, dataFiles, parkMode)` (step 3) and `mergeRaw(prevRaw, fetched, failedKeys)` (step 4).

Why: empty hitters and pitchers swap the whole app for the ErrorScreen (App.jsx:368-372), and `[]` on failure is what the hard path does today (:181-185, :195-199). A live refresh must never do that (critic item 3).

### 9.5 What the user sees

The sidebar footer (App.jsx:204-206) shows `Updating...` while `refreshing`, `Updated 21:04` after, and `Update failed; showing the previous data` when `refreshFailed`. When `tgs:control` says live refresh is off: `Live refresh is off. Press F5 after an update.` Tables keep sort, filters and hidden columns (PlayerTable.jsx:63-80 state stays mounted). The open player card stays open on the same player, with the new numbers, on all six pages that open one.

---

## 10. Control UI, nav and ErrorScreen (C)

### 10.1 App shell (App.jsx)

- Read `useLocation()` at the top of `App` (BrowserRouter wraps App, main.jsx:9).
- A `shell(content)` helper renders `<div className="flex h-screen bg-slate-950"><Sidebar .../><main ...>{content}</main></div>` (today's layout, App.jsx:374-456).
- New order of the early returns (today App.jsx:360-372):
  1. `leaguesLoading` (first manifest load only): the full-screen LoadingScreen, as today.
  2. Path starts with `/control`: `shell(<ControlPage .../>)` whatever the data state. The player data hook keeps loading underneath.
  3. `leagues.length === 0`: `shell(<ErrorPanel error="No leagues found." />)`.
  4. `loading`: `shell(<LoadingPanel .../>)` (LoadingScreen content with `h-full` instead of `h-screen`).
  5. `error`: `shell(<ErrorPanel error={error} />)`.
  6. No players in a player league (today :370-372): `shell(<ErrorPanel error={`No player data found for league "${currentLeague}".`} />)`.
  7. Otherwise today's routes.
- ErrorPanel text (replaces App.jsx:250-256): heading "This league's data could not be loaded", the error line, then "Pick another league in the menu on the left, or open Control, then Setup check, to see what is missing." with a link to `/control/setup`. No `extract_data.py` anywhere.
- The saved-league correction at App.jsx:272-282: on the first manifest load, behave as today. On a later refreshed list, if the current league vanished, switch the view to `leagues[0]` but do not write `tgs-league` to localStorage.
- Nav: one `NavLink to="/control"` with lucide `SquareTerminal` size 16, label "Control", placed between the scroll list and the footer (App.jsx:203/204), outside every `players &&` and feature guard. A dot shows the most urgent active job: amber pulsing (`bg-amber-400 animate-pulse`) when one waits for an answer, blue pulsing (`bg-blue-400 animate-pulse`) when one runs, slate (`bg-slate-500`) when one is only queued.
- Footer (App.jsx:204-206): the refresh status line (9.5) above the existing text.
- Default org: OrganizationPage.jsx:301 and WaiverClaimPage.jsx:55 become `orgs.find(o => o === myOrg) || orgs.find(o => /cub/i.test(o)) || orgs[0]`, where `myOrg = config.leagues[league]?.my_org` from `controlApi`. With the defaults this picks exactly what `/cub/i` picks today. The effect re-runs when `myOrg` arrives, until the user picks an org (9.4 table).

### 10.2 controlApi.js

- Module-level singleton (survives route changes and league switches, which unmount every route at App.jsx:365).
- On import: if `import.meta.hot` exists, send `tgs:hello`, wait up to 5 s for `tgs:token`. Then load `/__tgs/ping`, `/__tgs/config`, `/__tgs/catalog`, `/__tgs/jobs/active`. Listen to `tgs:job`, `tgs:catalog` and `tgs:control`.
- On a 401, send `tgs:hello` again once and retry.
- No plugin (`import.meta.hot` undefined or no token): Control shows "The Control page works only when the app runs from Launch TGS.bat." `ping` answering `control.on: false`: "The Control panel is off: <reason>. The app itself works. Run Check Setup.bat in the TGS Projections folder."
- Exports: `useCatalog()`, `useAppConfig()`, `useActiveJobs()` (list, oldest first), `useControlStatus()` (ping and `tgs:control`), `startJob(task, inputs, secrets)`, `answer(jobId, promptId, value)`, `stop(jobId, mode)`, `openEvents(jobId, handlers)` (EventSource with `?t=`), `getDoctor()`, `getSettings()`, `patchSettings(patch)`, `resetLocalSettings()`, `newLeagueOptions(type, version)`, `validateNewLeague(type, fields)`.
- `startConflict(task, activeJobs)` (pure, exported for tests): returns `{kind: "conflict", job, lock}` when an active job's `locks_held` shares a whole-run lock with `task.locks`, `{kind: "queue_full", job}` when another job is `queued` and the task needs the data lock, `{kind: "waits", job}` when the task needs the data lock and an active job holds it, else null.
- Secrets live in component state until `startJob` and are cleared right after the POST. Never in localStorage, URLs or logs.

### 10.3 ControlPage routes

| Route | Content |
|---|---|
| `/control` | One JobPanel per active job at the top (usually none, one or two), then task cards by group (4.1), hidden tasks left out. Groups collapse; the open state is stored in `tgs-control.groups` |
| `/control/jobs/:id` | One job: steps with status dots, log, summary |
| `/control/new-league` | NewLeagueWizard |
| `/control/setup` | SetupPanel: Python status, doctor results, settings form, Replace token |

Task card: title, description, time, flag notes, Run button. Flag notes (plain words):
- `drives_ootp`: "Takes over your mouse and keyboard. OOTP must be open inside a league. Hands off until it finishes. To abort, slam the mouse into a screen corner. If OOTP runs as administrator, use the .bat with Run as administrator instead: the app cannot click an OOTP that runs as administrator."
- `endless`: "Runs until you stop it."
- `heavy`/`long`: "Takes hours and a lot of memory."
- `needs_excel_closed`: "Close Excel on the league's sheets first. If a sheet is open, the task waits and asks you to close it."
- `network`: "Needs internet (statsplus.net)."
- `writes_app_data`: "Updates the app's data. The open app updates each league when the task finishes that league's steps."
- `read_only`: "Changes nothing. Can run while other tasks run."
- A `bat` field shows "Same as <bat>".

Run opens TaskForm: inputs whose `ask_when` is true (inputConditions.js with `catalog.state`), secrets as password fields (blank, or at least 8 characters; the browser checks this before the POST), confirm inputs as required checkboxes. Start follows `startConflict` (10.2):
- `conflict`: Start is disabled, with the reason in the lock's words (6.4), for example "Grind TGS is running (it uses OOTP and your mouse)."
- `queue_full`: Start is disabled: "Another task is already waiting. Start this one after it."
- `waits`: Start stays enabled and reads "Start (waits for <title>)".

JobPanel: title, status, elapsed, current step "4 of 19: TGS draft board", step list (status dots as App.jsx:225-230), log (`font-mono text-xs bg-slate-950 border border-slate-800 rounded-lg`, follows the bottom unless the user scrolls up), PromptCard when `waiting` (details in a log-style box, one button per choice), and:
- `queued`: "Waiting for <waiting_for.title> to finish." and a Cancel button (`after_step`).
- A countdown `message`: a large "Hands off: OOTP starts in N" line.
- "Stop after this step" (`after_step`), or "Stop after this cycle" (`after_cycle`) for endless tasks.
- "Kill now", after a confirm dialog: "Kill now ends the current step at once. A few steps write their files in place, so a killed step can leave one half-written file (its .bak copy stays). If the step drives OOTP, the app releases the keys and the mouse, but OOTP keeps simming: stop it inside OOTP."
- `stale: true`: "This task is not responding." next to Kill now.
- Console jobs show "Running in a console window" and the same Stop buttons (run_task honors them).
- At the end: the summary lines (FAILS list or pull report verdict) and a status word: Finished, Finished with problems, Failed, Stopped, Killed, Lost, Did not start. `invalid` shows its `message`, and a Run button for its `fix_task` when there is one (for example "Rebuild ratings archive").
- A `lost` or `failed` New League job shows "Clean up unfinished league", which starts `new_league_cleanup` with that job's id (12.6).

Styling follows the existing pages: cards `bg-slate-900/60 border border-slate-800 rounded-xl`, tab buttons as CalibrationPage.jsx:214-217, header block as CalibrationPage.jsx:197-210, lucide icons (`Play`, `CircleStop`, `RefreshCw`, `Plus`, `Settings` exist in the installed lucide).

### 10.4 NewLeagueWizard

1. Pick a type (four cards, plain words):
   - "Online league on StatsPlus": "Pulls ratings from statsplus.net with your league's token. Prices players with TGS's or BLM's calibration."
   - "Local OOTP save": "Reads a save's database CSV export, like Regular Game."
   - "DEV research league": "An all-AI OOTP league you sim in place. Adds a Rating Trends page from its yearly dumps."
   - "Calibration clone league": "Makes and sims clone leagues from a pristine master save. No app league. Turning the clones into a calibration is an advanced manual job (see STATUS.md and engine/calibrate.py)."
2. Fields per type (12.1). Save names and versions are dropdowns from `/__tgs/new-league/options`; a save name cannot be typed. For an online league the token field names the exact line it fills: "This goes on the line `<SLUG>=` in StatsPlus Tokens.txt." The browser checks the token's shape (`^[A-Za-z0-9_-]{20,80}$` after trimming) before Review.
3. Review: `POST /__tgs/new-league/validate`; show errors next to fields, warnings, the known limits (12.3) and the step plan with what each step writes.
4. Start: `startJob('new_league', {type, ...fields}, {token?, sessionid?, csrftoken?})`, then the JobPanel. On success: "League added. Pick it in the league menu." The league list and the task cards update by themselves (`tgs:data` for leagues.json, `tgs:catalog`). On a failure, stop or kill, the job page says what the rollback undid.

A league added here gets a "Remove <name> from the app" card (`remove_league.<ID>`, 12.5). Its form asks the user to type the id.

### 10.5 SetupPanel

- Top line from `ping.python`: "Python: 3.13.14 (python)", or the plain fix: `ENOENT` and `9009` give "Install Python 3.13 from python.org and tick Add python.exe to PATH. Then close the Launch TGS window, start it again, and press Check again." Check again probes Python again (`ping?probe=1`); when Python now starts, the page reloads the task list and the settings form. While Python does not start, `GET /settings` answers from the two files in Node with only the three commands and `python_failed`, so the Python (main) field can still be fixed.
- "Run the check" calls `GET /__tgs/doctor`; one row per check (status dot, title, detail, fix text, and a Run button when the check names a `task`). `fail` rows first, then `warn`, then `ok`.
- Settings form for the whitelisted keys (8.5): Python main and ML commands (argv shown space-joined; split on spaces, quotes keep a path with spaces together), Node command, OOTP saved_games per version, per league: enabled, name, my team (park home), my org (default org), OOTP save and version. A `bad_interpreter` answer shows its output under the field and saves nothing.
- "Reset local settings" (shown when `settings_local` is true, and always when the catalog reports `settings_error`): confirm dialog "This renames settings.local.json to settings.local.bad-<time>.json and goes back to the default settings. No league data is touched. Leagues you added with New League keep their data and stay in the league menu, but their tasks disappear until you fix the file and rename it back.", then `resetLocalSettings()`.
- "Replace a StatsPlus token": a league dropdown and a password field, which start `token_set` (4.6). The line it writes is shown under the dropdown.
- After a `my_team` change: "Run Update park factors to apply this." After a save: re-run the check.

---

## 11. Refactor sites (D)

Rule for every site: the new value comes from settings and equals today's value with `settings.defaults.json` and no local file. `test_settings_defaults.py` proves each row (14.3).

| # | File:line at ef23800 | Today | Change |
|---|---|---|---|
| 11.1 | `tgs-viz/ingest/statsplus_token.py:31-32, 37-46, 50-52, 308-318` | `FILE_NAME`, `LEAGUES = (("TGS","tgs"),("BLM","blm"))`, TEMPLATE with `TGS=` and `BLM=` | `LEAGUES` = `[(id, slug) for id, slug in ST.slug_map().items()]`; TEMPLATE lines are `slug.upper() + "="`, one per entry, because the file is keyed by slug (`_read` keys each line by its lowercased name, :138; `_set_line` writes `slug.upper()`, :288). CRLF, same comment lines; bytes equal for the defaults, where id and slug agree. `default_token_file()` from `ST.token_file()`; `_leagues()` accepts any enabled online id, maps it to its slug, and its error lists them. Add `ensure_line(slug)`: adds `<SLUG>=` only when no line for the slug exists (uses `_set_line`, :279-298) |
| 11.2 | `tgs-viz/ingest/pull_report.py:31-32` | `LEAGUES`, `SLUGS` | Add `--leagues A,B`. No flag: `["TGS","BLM"]` filtered to enabled online leagues. `SLUGS` from `ST.slug_map()`. One-league wording: "Updated." / "not pulled this run" |
| 11.3 | `tgs-viz/backtest/ratings_db.py:73, :1194` | slug dicts | `LEAGUES = ST.slug_map()`; `:1194` uses `ST.slug(lg)` |
| 11.4 | `tgs-viz/ingest/refresh.py:242-248, :252, :260` and pricing calls | in-place `write_json`; `{"TGS":"tgs"}.get(...)`; calibration = `--league` | `write_json` keeps the `.bak-<stamp>` copy, then writes `<target>.<pid>.tmp` and `os.replace`s it onto the target (10 tries, 200 ms apart, on `PermissionError`), so a kill mid-write can never leave a truncated hitters.json or pitchers.json (works-and-safe review, item 21). Same bytes as today. Slug default `ST.slug(league)`. New `--calib <TGS or BLM>` (default = league): every `R.live_*`, `R.run_hitters`, `R.run_pitchers`, `drift_check` and `_live_datapoints` call uses the calib league. Output dir, archive (`rdb.append_pull`), raw cache, `drop_foreign` and `enrich_org_lev` keep the league id. When calib != league: no park blend exists for the league, so write the `*_park.json` files as copies of the neutral results (as export_league does) and skip `park_values` (park_lineup_values.json) |
| 11.5 | `tgs-viz/ingest/draft.py:72-78, 86-97, 151, 355` | OOTP paths, slug dicts | `DEFAULT_CSV` built from `ST.ootp_save_dir(lg)` plus today's file names (same group structure); slug `ST.slug`; `--calib` in `main()` (:290-304) and `dispersal_main()` (:426-437); `_save_json` retries `os.replace` (10 tries, 200 ms) on `PermissionError`. `ST.ootp_save_dir` answers for a pending league too (3.2), so a new online league's first pull finds its save |
| 11.6 | `tgs-viz/ingest/r5.py:29-37` | | `DEFAULT_CSV` from `ST.ootp_save_dir` |
| 11.7 | `tgs-viz/ingest/iafa.py:32-42` | | same |
| 11.8 | `tgs-viz/ingest/statsplus.py:1280-1287, 1302-1312` | unknown league falls back to TGS tables | `drop_foreign`: TGS and BLM unchanged; any other league uses `set(ST.league(id)["foreign_league_ids"])` (default empty; pending leagues included). `_lev_for`: `TGS` uses `LEAGUE_TO_LEV`; every other league uses the LgLvl branch (today's BLM branch). Default params stay `"TGS"` |
| 11.9 | `tgs-viz/ingest/statsplus_history.py:218, 221, 227, 847` | `SLUGS`, `FIRST_KNOWN`, `PROBE_YEARS`, choices | From `ST.slug_map()` and `ST.history_settings()` (leagues with `history.first_date`) |
| 11.10 | `tgs-viz/ingest/metadata_inputs.py:62` | `SLUGS` | `ST.slug_map()` restricted to `LEAGUE_DIRS` keys (:61 stays) |
| 11.11 | `tgs-viz/backtest/growth_lenses.py:119` | `LEAGUE_SLUG` | `ST.slug_map()` |
| 11.12 | `tgs-viz/ingest/build_scurve_preview.py:41` | slug dict | `ST.slug(lg)` |
| 11.13 | `tgs-viz/ingest/parks.py:41-51` | `"home"` values | `home` from `ST.league(lg)["my_team"]`; `exclude` and `workbook` stay in code |
| 11.14 | `ootp/winsim.py:53-77, 81, 101-105, 263` | install discovery, `PROTECTED`, `load_profiles` | `GAMES`: discovery as today, then each `ootp.installs.<v>.saved_games` that exists replaces that version's `saved`. `PROTECTED = ST.protected_saves()` = `ootp.protected_extra` plus the lowercased `ootp_save` of every `statsplus` and `local_export` league, disabled and pending ones included (`leagues(include_disabled=True)`: turning TGS off on the Setup page must not unprotect its save). Never `dev` or `clone` leagues: `continuous_plan` calls `guard(folder)` (winsim.py:1174, guard at :701-703), so protecting "dev tests" would block Sim Dev League (critic item 9). Default result: `{"new game","thegrandestsalami","blm","regular game"}` = today. `load_profiles()` returns the file merged with settings `ootp_profile` entries (file wins on a clash; New League refuses clashes). Add `--reset-input` (3.5): `reset_input()` (:263), then exit 0 |
| 11.15 | `ootp/cleanup_clones.py:27-35, 56, 75-89, 106-110` | `ALLOW`, `league_profile`, choices, the skip rule, `input` | `league_profile` via `winsim.load_profiles()`; `--league` choices = profiles with a `prefix`; `ALLOW` keeps TGS and BLM literals and derives `[re.escape(prefix) + r"\d+"]` for other leagues. The skip rule (:82-83) also skips every name in `ST.league_saves()` (every configured league's save, any type, enabled or not) and the `master` of every profile in `winsim.load_profiles()`, not only this league's master. So BLM's `[1-5]` pattern can never delete a dev league's save named "5". The "NOT touched" line (:106) lists them too. Add `--dry-run` (3.5); wrap `input` in `try/except EOFError` and treat it as no, printing `  skipped (no answer).` |
| 11.16 | `tgs-viz/backtest/dump_source.py:45, 112-118, 128-134` | profiles file, saved_games dirs | `profile()` reads `ST.ootp_profiles()`; `saved_games_dirs(game)` puts `ST.saved_games(game)` first, then today's candidates |
| 11.17 | `tgs-viz/ingest/export_league.py:87-89, 203-210` | `csv_dir_for`, `write_json` | `csv_dir_for` uses `ST.saved_games(game)` when set, else today's path; `write_json` retries `os.replace`. `RESERVED` (:82) and `--calib` choices (:220) stay |
| 11.18 | `tgs-viz/extract_data.py:356-368` | `upsert_manifest` writes in place | Atomic write (tmp in the same folder, `os.replace` with retry), opened in text mode with the default newline exactly as today, so the file keeps its CRLF bytes. Add `remove_manifest_entry(manifest_path, league_id)` (same atomic write). Output bytes unchanged |
| 11.19 | `tgs-viz/ingest/sync_datapoints.py:376` | `input` | EOF guard: treat as no, print `  skipped (no answer).` |
| 11.20 | `ootp/ingest_dumps.py:388` | `input` | Same EOF guard |
| 11.21 | `tgs-viz/backtest/ml/score.py:239-242` | `os.replace` | Retry on `PermissionError` |
| 11.22 | `tgs-viz/backtest/ratings_db.py:152-153` | `connect()` creates a missing database | Guard: when `db_path` does not exist and `<folder of db_path>/vintages/*/_pulls.csv` exists, raise `SystemExit("The ratings archive is missing. Rebuild it first: Control, Setup check, Rebuild ratings archive (or python tgs-viz\backtest\vintage_backup.py --restore).")`. `RATINGS_DB_ALLOW_NEW=1` (worktree tests only) skips the guard. `vintage_backup.restore` opens the database with `sqlite3.connect` itself (vintage_backup.py:121), so the guard never blocks it. On the user's PC the database exists, so nothing changes. Add `forget_league(conn, league)`: deletes that league's rows from `ratings` and `pulls` in one transaction (the pattern at :347-348); only New League rollback calls it (12.2) |
| 11.23 | `tgs-viz/ingest/statsplus_token.py:206-226` | `saved_info` and `age_warning` write the first-seen file (`_seen` calls `_write_seen` when the token is new) | Add `token_age(slug)`: reads the seen file and the token, writes nothing. Returns `{"days": n}` when the seen entry matches the current token, `{"days": None, "new": True}` when the token is new to the file. doctor uses only this (13.1) |

Why the write retries: the app may read a file at a step end (9.3) while the next step replaces it. On Windows `os.replace` can fail while another process reads the target (ratings_db.py:1503-1505 and park_values.py:70-71 already note this). Without a retry the next step could fail.

Out of scope for D (research constants or not must-configure; keep in code): `calibrate.py:282` and `sync_datapoints.py:35` sheet folder maps, `f"The Sheets {league}"` builders, argparse `[TGS, BLM]` choices in the fit scripts, `ml/common.py` `BASES`, `dev_signals.py` `LEAGUES` and `PREV_ORG_RULE_LEAGUES`, `hitters.py:94`, `currency_fit.py:58`, `promote_scurves.py:40`, winsim button templates and timings, `ratings_db.py:641`, the app's `LEAGUE_TEAMS`, `leagueCalib.js`, `rosterOptimizer.js:843`, `orgAbbr.js`, `MockDraftPage.jsx:19-20`, `SeriesPlannerPage.jsx:15`, `positional_strength_report.mjs:7`, workbook `Filters!C3` (critic item 18).

---

## 12. New League (D backend, A task, C UI)

### 12.1 Fields and validation

Common: `id` (`^[A-Z0-9]{2,8}$`; not a Windows device name: `CON`, `PRN`, `AUX`, `NUL`, `COM0` to `COM9`, `LPT0` to `LPT9`; not in settings leagues; not in `leagues.json`; not `TGS`, `BLM`, `DEV`; no folder `tgs-viz/public/data/<id>`; no `ootp/leagues.json` key with that id; no rows for that id in the ratings archive (a read-only `SELECT 1 FROM pulls WHERE league=? LIMIT 1`) and no folder `tgs-viz/backtest/vintages/<id>`: "This id was used before. Pick another id."), `name` (1 to 40 characters), `my_org` optional.

Every save name field (`ootp_save`, `master`) must be one of the names `options` returned for that version (12.2), compared exactly. A typed path such as `..\..\x` can never pass.

| Type | Fields | Checks (no network) |
|---|---|---|
| `statsplus` | `slug`, `basis` (TGS or BLM), token (secret, optional), `ootp_version` and `ootp_save` (optional, for draft/R5/IAFA exports), `history_first_date` (optional, `YYYY-MM-DD`), `foreign_league_ids` (optional) | slug pattern; slug not used by another league; `engine/calib/<basis>/constants-latest.json` exists; save in the options list when given. The token never reaches `check` (the spec holds no secrets): the browser checks its shape (10.4) and the `token` step checks it again with `statsplus_token.read_value`. If no token is given and none is saved for the slug: the cookie pair becomes required for the first pull |
| `local_export` | `ootp_version`, `ootp_save`, `basis` (default BLM for 27, TGS for 26) | save in the options list; `<saved_games>/<save>.lg/import_export/csv/players.csv` exists; save not a clone name |
| `dev` | `ootp_version`, `ootp_save`, `dump_dir` (optional), `years` (default 5), advanced `resume_after` 600, `nostart_abort` 1800 | save in the options list; save not in `protected_saves()`; save not any profile's `master`; warn when `<save>.lg/dump` is missing ("Turn on Export CSV files after each simulated season in this league") |
| `clone` | `ootp_version`, `master`, `prefix` (default `0` + id lowercased), `start_year` 2016, `target_year` 2026, `runs` 10 | master in the options list; prefix `^[0-9a-z_-]{2,12}$`; error (not a warning) when any existing save matches `^<prefix>\d+$` (case-insensitive) or any name in `ST.league_saves()` or any profile master matches it: cleanup `--junk` deletes every save that matches the pattern and has no complete dumps (cleanup_clones.py:85-89), and a real save has none |

### 12.2 new_league.py subcommands

All print plain lines; `--json` prints one JSON object. Exit 0 ok, 2 invalid or failed. `--manifest <path>` (tests only) points `register`, `register-manifest`, `remove` and `rollback` at a copy of leagues.json.

| Command | Does |
|---|---|
| `options --type T [--version V] --json` | `{"versions": [{"version": "27", "saved_games": "...", "exists": true}], "saves": ["Regular Game", ...], "bases": ["TGS","BLM"]}` (saves = `.lg` folder names, clones and protected names marked) |
| `check --spec F [--precheck-out P] [--json]` | Validate (12.1). Prints `{ok, errors: {field: msg}, warnings: [], plan: [{title, writes}], needs_credentials}`; `needs_credentials` is true for `statsplus` when no token is saved for the slug, and the wizard then requires the token or both cookies. With `--precheck-out`, also writes `P`: `{data_dir_existed, manifest_had_id, settings_had_id, token_line_existed, vintages_dir_existed, archive_had_id}`. The task passes `--precheck-out "<job>\precheck.json"`; B's validate call never does |
| `token --spec F` or `token --league ID` | `--league` reads the slug from settings (the `token_set` task). `TGS_NL_TOKEN` set: check it with `statsplus_token.read_value` (a bad shape prints the counts-only problem and exits 2), then `statsplus_token.save(slug, token)` and print "Saved the StatsPlus token on the line <SLUG>= in StatsPlus Tokens.txt." Else `ensure_line(slug)`, print "Added an empty <SLUG>= line to StatsPlus Tokens.txt. Paste the token there before the next update." Never prints the token |
| `profile --spec F` | Write `leagues.<id>` with `type`, `name`, `pending: true` and the type's fields into settings.local.json: `slug`, `basis`, `ootp_version`, `ootp_save`, `history`, `foreign_league_ids` for `statsplus`; `ootp_version`, `ootp_save`, `basis` for `local_export`; `ootp_version`, `ootp_save`, `ootp_profile` for `dev` and `clone` |
| `register --spec F` | Remove `pending` from the settings entry. Then the manifest entry, only when the data files exist: `statsplus`: `extract_data.build_manifest_entry(id, name)` plus `{"basis", "source": "StatsPlus", "slug"}` through `upsert_manifest`; `local_export`: export_league already registered it, so verify it is there; `dev`: the `register-manifest` call below when `<id>/rating_trends.json` exists, else print "It appears in the app after its first banked season."; `clone`: nothing more (no app league) |
| `register-manifest --league ID` | Exactly `extract_data.upsert_manifest(path, [extract_data.build_manifest_entry(ID, name=N)])` when `<ID>/rating_trends.json` exists, `N` = the manifest's name for ID, else the settings name (4.5). Used by `update.<dev ID>` |
| `rollback --spec F --precheck P` | Uses `P`. Moves `tgs-viz/public/data/<id>/` to `<control>/rollback/<job_id>/<id>/` when it did not exist before (move, never delete). Moves `tgs-viz/backtest/vintages/<id>/` to `<control>/rollback/<job_id>/vintages-<id>/` when it did not exist before. When `archive_had_id` is false, calls `ratings_db.forget_league(conn, id)` (11.22), so a failed first try does not burn the id. Removes the manifest entry when it was not there before (`remove_manifest_entry`). Removes the settings entry when it was not there before. Keeps the token line (the user's own input). Prints what it did. Safe to run twice |
| `remove --league ID` | Only for a league whose settings entry exists only in settings.local.json (`added_by_wizard`). Moves `tgs-viz/public/data/<ID>/` to `<control>/removed/<ID>-<stamp>/`, removes the manifest entry and the settings entry. Keeps the archive rows, the vintages folder and the token line, so the id stays used (12.1) and nothing that took hours to build is lost |

### 12.3 The new_league task (A expands steps from `inputs.type`)

The task's `id` input carries the pattern `^[A-Z0-9]{2,8}$`, so run_task refuses a bad id before it builds lock names or job files from it. run_task writes the non-secret inputs to `<job>/new_league_spec.json` and passes it as `{spec}`, and `<job>\precheck.json` as `{precheck}`. The task has `rollback: {"run": ["@py", "tgs-viz\\tools\\new_league.py", "rollback", "--spec", "{spec}", "--precheck", "{precheck}"], "until_step": "register"}`. run_task runs it when the job ends `failed`, `stopped` or `killed` before `register` finished ok, then keeps that status. A runner that dies leaves the job `lost`; the cleanup task covers that (12.6). After `register`, nothing is rolled back: the league exists, and a failed later step leaves it `partial` like any update.

`statsplus`:
```
@py "tgs-viz\tools\new_league.py" check --spec {spec} --precheck-out {precheck}         [fail]
@py "tgs-viz\tools\new_league.py" profile --spec {spec}                                  [fail]
@py "tgs-viz\tools\new_league.py" token --spec {spec}          env TGS_NL_TOKEN (secret 'token') this step only   [fail]
@py "tgs-viz\ingest\refresh.py" --statsplus --league {id} --slug {slug} --calib {basis} --write   [fail] {app}   env cookie if given
@py "tgs-viz\ingest\draft.py" --league {id} --slug {slug} --calib {basis} --write       [collect draft] {app}
@py "tgs-viz\tools\new_league.py" register --spec {spec}                                 [fail] {app}
@py "tgs-viz\backtest\ratings_db.py" --export --league {id}                              [collect trends] {app}
@py "tgs-viz\backtest\dev_signals.py" --league {id} --write                              [collect dev-signals] {app}
@ml "tgs-viz\backtest\ml\dataset.py" --basis {id} --score-only --write                   [collect ml-rows]
@ml "tgs-viz\backtest\ml\score.py" --league {id} --write                                 [collect ml-score] {app}
```
`profile` comes first so the first pull runs with the league's settings: `drop_foreign` reads `foreign_league_ids` (11.8) and `draft.py` builds its CSV path from `ST.ootp_save_dir(id)` (11.5). The entry is `pending`, so no task card appears for it yet. Order matters after `register` too: `dev_signals` and the ML scripts accept the league only after `register` writes its manifest entry with a `basis` (dev_signals.py:1079-1088, ml/common.py:94-122).

`local_export`:
```
check --precheck-out {precheck} [fail]
profile [fail]
@py "tgs-viz\ingest\export_league.py" --league {id} --name "{name}" --save "{ootp_save}" --game {ootp_version} --calib {basis} --write   [fail] {app}
register [fail]
@py "tgs-viz\backtest\dev_signals.py" --league {id} --write                    [collect]
@ml "tgs-viz\backtest\ml\dataset.py" --basis {id} --score-only --write         [collect]
@ml "tgs-viz\backtest\ml\score.py" --league {id} --write                       [collect]
```
export_league writes every data file first and registers the manifest entry last (export_league.py:288-340), which already meets the "data before manifest" rule.

`dev`:
```
check --precheck-out {precheck} [fail]
profile [fail]
@py "tgs-viz\backtest\dump_vintages.py" --league {id} --write [--dump-dir "{dump_dir}"]   [fail]
@py "tgs-viz\backtest\ratings_db.py" --export --league {id}     [ignore]   (exit 4 = no dumps yet)
register [fail]
```
`clone`:
```
check --precheck-out {precheck} [fail]
profile [fail]
@py "ootp\winsim.py" --league {id} --runs 1 --dry-run           [fail]
register [fail]
```

Known limits the wizard states:
- `statsplus`: My Park equals Neutral (no park factors for the league); the Series Planner says its file is missing; draft boards need the OOTP draft-pool export in the save's import_export folder; dev signals treat the league like an exported league (the out-of-org rule in dev_signals.py:164 covers TGS and BLM only); Get StatsPlus History works only when a history start date is given.
- `dev`: the measured age curve and the ML models still come from DEV (ageCurve.js:18, ml/common.py:90). A second dev league adds its own Rating Trends page.
- `clone`: no app league; calibration from the clones is manual.

### 12.4 How the new league's tasks appear

`register` removes `pending` from settings.local.json. B sees the change (settings.local.json is in `state.watch_files`, 3.4; B also rebuilds the catalog at every `job_end`) and broadcasts `tgs:catalog`. The Control page shows `update.<ID>` (and `sim_dev.<ID>` or the clone tasks, and `remove_league.<ID>`) in the "Your leagues" group. The league picker updates from the `tgs:data` event for leagues.json.

### 12.5 Removing a league added by the wizard

`remove_league.<ID>` exists only for leagues with `added_by_wizard` (3.4), never for TGS, BLM, RG or DEV. Its form has one required text input, `confirm_id`, which must equal the id (`--validate` and B check it). The step is `new_league.py remove --league <ID>` (12.2). If the open league is the one removed, the app switches the view to `leagues[0]` without writing `tgs-league` (10.1).

### 12.6 Cleaning up after a lost New League job

A runner that dies (PC restart, `--kill`) cannot run its own rollback. Its job page shows "Clean up unfinished league", which starts `new_league_cleanup` with that job's id (4.6). The step runs `rollback` with that job's spec and precheck files, which `--reap` keeps (7.6). `rollback` is safe to run twice. It does nothing to a league whose `register` step finished: it reads the job's `state.json` and refuses when that step ended ok, and it also refuses when a later New League job registered the same id or the id was removed after the job started (a later `remove_league.<ID>` job or a `<control>/removed/<ID>-<stamp>` folder). The precheck alone cannot tell, because it is written before the run and always shows the league as new. The job page offers the button only when the job's `register` step did not end ok.

---

## 13. doctor.py and requirements (D)

### 13.1 Checks

No network. No writes (tokens use `token_age`, 11.23; the archive and job checks open files read-only). Under 20 s on this PC. Never prints a token value (only "present", "empty", "looks wrong: N characters"). Checks for disabled leagues are skipped.

Severity rule: `fail` only when the app or the Control page cannot work (Node, the app packages, the settings files), or an enabled league in leagues.json cannot load. Everything else is `warn` or `ok`, and every `warn` says which task needs it. On a fresh PC the committed defaults name the author's leagues and saves; those show as warnings, so the check does not bury a new user in failures.

| id | Title | Status rule | Fix (plain words), task |
|---|---|---|---|
| `python.main` | Python (main) | runs `interp("main") -c` probe: version, executable. `warn` when it cannot start or is under 3.11 (the app still opens; every task needs it) | "Install Python 3.13 from python.org and tick Add python.exe to PATH, or set the command on the Setup page." When `python` fails and `py -3` works: "Set Python (main) to py -3 on the Setup page." |
| `python.main.packages` | Packages (main) | openpyxl, numpy missing: `warn` ("needed by every update task"); pyautogui, win32gui (pywin32), cv2 (opencv-python), PIL (Pillow) missing: `warn` ("needed only for Grind, Sim Dev League and the OOTP tools") | "Run: python -m pip install -r requirements.txt" |
| `python.ml` | Python (ML) | same probe for `interp("ml")`; `warn` ("needed for ML dev scores; without it the app uses the older cell method") | "Install Python 3.14, or set the ML command on the Setup page." |
| `python.ml.packages` | Packages (ML) | numpy, pandas, sklearn missing: `warn` (same reason) | "Run: py -3.14 -m pip install -r requirements-ml.txt" |
| `node` | Node.js | `node --version` >= 20.19 or >= 22.12 (Vite 7 engines); `fail` otherwise | "Install Node.js 22 LTS." |
| `node_modules` | App packages | `tgs-viz/node_modules/.bin/vite.cmd` exists and `node_modules/vite/package.json` version starts with 7; `fail` otherwise | "Open a terminal in tgs-viz and run: npm install" |
| `settings` | Settings | both files parse and validate; `fail` otherwise (the Control page cannot list tasks) | names the file and key; "Or press Reset local settings on the Setup page." |
| `tokens` | StatsPlus tokens | per enabled online league: present / empty / looks wrong, as `warn` when not present; age from `token_age` (warn after 80 days) | "Paste the token from statsplus.net/<slug> Prefs on the line <SLUG>= in StatsPlus Tokens.txt, or use Replace a StatsPlus token on the Setup page." task `token_set` |
| `ootp.<ver>` | OOTP <ver> saved games | folder exists, number of `.lg` folders; `warn` when missing ("needed by <tasks of leagues on this version>") | "Set the saved_games folder on the Setup page." |
| `league.<ID>.save` | <name>: OOTP save | `ootp_save_dir` exists (skip when unset); DEV: `dump` folder exists (a junction is fine); `warn` | |
| `league.<ID>.data` | <name>: app data | in leagues.json; player league: hitters.json and pitchers.json exist, are not empty, start with `[` and end with `]` (`--deep` parses them); trends-only: rating_trends.json exists. `fail` when the league is in leagues.json and its files are missing or broken (picking it shows the error panel) | "Run Update <name> on the Control page, or turn this league off on the Setup page." task `update.<ID>` |
| `ratings_db` | Ratings archive | missing while vintages exist: `warn` ("every update task refuses until it is rebuilt"); present: compares the pull count per league (`SELECT league, COUNT(*) FROM pulls GROUP BY league`, opened with `mode=ro`) with the rows of `vintages/<LG>/_pulls.csv`; fewer pulls than vintages: `warn` | Missing: "Rebuild it from the saved vintages." task `restore_ratings_db`. Short: "The archive has fewer pulls than the saved vintages. Rename tgs-viz\backtest\ratings_history.db, then run Rebuild ratings archive." |
| `ml_models` | ML dev models | `tgs-viz/backtest/.dev_cache/ml/models` has files; `warn` otherwise | "The app uses the older cell method until Bank Dev Seasons trains the models." |
| `git_ignore` | Secrets stay off GitHub | `git check-ignore -q "StatsPlus Tokens.txt"` and `settings.local.json` (skip when git is missing); `warn` | |
| `jobs` | Control jobs | `joblock` read-only: active entries and lock files whose runner is gone (7.6). The job named by `TGS_JOB_ID` is doctor's own and never counts. `warn` per stale job; `warn` for lock or active files that cannot be read | "A task ended without cleaning up (<title>). The next task cleans it up." Unreadable files: "Run this in the TGS Projections folder to remove them: python tgs-viz	ools
un_task.py --reap" |
| `leagues.pending` | Unfinished new leagues | shown only when settings.local.json holds a `pending` league that no running New League job owns; `warn` | names the New League job page to open and press Clean up unfinished league, or, when that job folder is gone, the entry to delete from settings.local.json |

### 13.2 Output

Text (default): one line per check, `[ OK ] Title: detail`, `[WARN]`, `[FAIL]`, `[SKIP]`, with the fix on the next line indented four spaces. Last line: `Setup check: N problems, M warnings.` Exit 0 when there are no `fail` rows, else 1. The `doctor` task maps exit 1 to "Finished with problems" (`report_verdict: lenient`).

`--json`: `{"schema": 1, "ok": bool, "checks": [{"id", "title", "status": "ok|warn|fail|skip", "detail", "fix", "task"}]}`. A `SettingsError` is caught and becomes the `settings` row; doctor never crashes on bad settings.

### 13.3 Requirements files (repo root)

Minimums = the versions installed on this PC on 2026-10-01 (`python -m pip list` on Python 3.13.14, `py -3.14 -m pip list` on Python 3.14.3). They need Python 3.11 or newer (numpy 2.4), the one minimum used everywhere (rule 1.4).

`requirements.txt` (the `python` interpreter):
```
# Main Python (the "python" command), Python 3.11 or newer.
# Install: python -m pip install -r requirements.txt
openpyxl>=3.1.5
numpy>=2.4.2
# Only for Grind, Sim Dev League and the OOTP tools (screen automation):
pyautogui>=0.9.54
pywin32>=312
opencv-python>=5.0.0.93
Pillow>=12.1.1
```
`requirements-ml.txt` (the `py -3.14` interpreter):
```
# ML Python (the "py -3.14" command). Install: py -3.14 -m pip install -r requirements-ml.txt
numpy>=2.3.4
pandas>=2.3.3
scikit-learn>=1.7.2
```
xgboost is left out (research script only, ml/gpu_compare.py:40).

### 13.4 .gitignore additions

```
# Control panel: local settings, bad settings copies and job folders (never committed)
settings.local.json
settings.local.bad-*.json
/.control*/
# Vite caches of worktree test servers
/.vite-cache*/
/tgs-viz/.vite-cache*/
*.tmp
# Excel lock files hold the Windows user name
~$*
# winsim diagnostic screenshots
ootp/_diag_*.png
```

---

## 14. Proof that the user's setup is unchanged

### 14.1 Bat equivalence test (A)

`python tgs-viz\tools\tests\test_bat_equivalence.py` must print `18 bats, N scenarios, all equal` and exit 0.

- `batsim.py` interprets the legacy bats (`legacy_bats/*.bat.legacy`) and supports exactly what they use: `@echo off`, `title`, `setlocal`/`endlocal`, `cd /d`, `echo`/`echo.`, `rem`/`::`, labels, `goto`, `set "X=..."`, `set X=...`, `set /a X+=1`, `set /p X=prompt`, `%VAR%` and `%~1` and `%%` expansion, `if errorlevel 1 ...`, `if not errorlevel 1 ...`, `if defined X ...`, `if not defined X ...`, `if /i "%A%"=="B" (... & ... & goto x)`, `if "%A%"=="2" goto x`, `if exist "p" (...) else (...)`, `if not exist "p" (...)`, multi-line `( ... )` blocks, `pause`, `exit /b N`, and external commands (`python`, `py -3.14`). External commands are recorded, not run; their exit codes come from the scenario. `%USERPROFILE%` comes from the scenario env. `set /p` with a blank answer sets errorlevel 1 in cmd; batsim may ignore that, because in every legacy bat an external command runs before the next errorlevel test or the end of the file.
- batsim reads each fixture with CRLF and LF both accepted (four legacy bats are LF-only, critic item 14).
- batsim applies cmd's caret rules to `echo` lines after `%` expansion: outside double quotes, `^` drops and keeps the next character (`^>` prints `>`, `^(` prints `(`, `^-` prints `-`, `^^` prints `^`); inside double quotes it stays. `errorlevel` follows cmd: a code of 2^31 or more is negative, so `if errorlevel 1` is false for it.
- Golden lines, checked against both batsim and run_task, so the two cannot agree on raw carets:
  - Grind TGS.bat:9 prints `  AUTOMATICALLY recalibrates (constants -> sheets -> webapp),`
  - Get StatsPlus History.bat:112 (league TGS) prints `  STOPPED (code 2): no StatsPlus login. No token is saved for TGS and`
  - Sync Metadata.bat:6 prints `  Sync Data Points  -  Metadata  ->  Sheets`
  - Get StatsPlus Ratings.bat:15 prints `   F12  ->  Application (or Storage)  ->  Cookies  ->  statsplus.net`
- Output per scenario: the ordered list of `(argv, STATSPLUS_COOKIE value or None)`, prompt texts in order, `pause` positions (except the final one), the printed echo text, the exit code.
- Scenarios (every combination):
  - Get StatsPlus Ratings: tokens {both, TGS only, BLM only, none} x SID {blank, given} x each command failing alone, plus all passing, plus pull_report 0 and 1.
  - Get StatsPlus History: typed league {tgs, TGS, BLM, x then TGS} x token {yes, no} x history exit {0, 1, 2, 3, 6, 7, 8, 9, 10, 3221225786} x one later step failing.
  - Bank Season, Update Draft Board, Update Regular Game, Update Dispersal Board: all pass, each command failing alone.
  - Bank Dev Seasons, Recalibrate TGS, Recalibrate BLM, Sync Metadata, Sim Dev League: all pass, each command failing alone; Sync Metadata x metadata-latest.json {exists, missing}; Sim Dev League x argument {none, 3} x dump_vintages.py {exists, missing}.
  - Grind TGS and BLM: 2 cycles, winsim failing in cycle {none, 1, 2}, each fail-fast step failing in cycle 1.
  - The five ootp bats: one scenario each (no checks in them).
  - Ctrl+C codes: Get StatsPlus Ratings with `TGS-draft` ending 3221225786; Bank Dev Seasons with `dev_odds` ending 3221225786; Grind TGS with winsim ending 3221225786 in cycle 1. Each is compared under allowed difference 2.
- run_task side: `run_task.py --plan <task> --mode console` with the same inputs and assumptions, interpreters from the defaults.
- Allowlisted differences (the only ones):
  1. `update.RG`: the export_league argv may carry `--game 27 --calib BLM` (both equal export_league.py's defaults at :219-220).
  2. A step whose exit code is 2^31 or more (3221225786 in the scenarios) counts as failed in run_task (6.4); batsim, like cmd, counts it as a success under `if errorlevel 1`. The test checks run_task's exact expected outcome for each such scenario: `TGS-draft` lands in FAILS; Bank Dev Seasons goes to its fail block with exit 1; Grind stops after the cycle as with any winsim problem. In History both sides agree (FAILS gets `TGS-history`).
- Job mode check: for each task, the job plan equals the console plan after applying the substitutions in 6.3 and nothing else.
- Text report: every console line that differs from the legacy echo text (after caret rules) is listed with its rule number from 6.5. Any other difference fails the test.
- Wrapper check: every wrapper file is CRLF only, ASCII, holds the legacy `title` and `cd` lines, then exactly the template lines of 6.5 with the right task id.
- Backup check: each file in `old bats (backup)` equals its legacy fixture after line-ending normalization, except the one `cd` line (6.7).
- Attributes check: `git check-attr text eol -- "Grind TGS.bat"` reports `eol: crlf`; `git check-attr text -- "tgs-viz/tools/tests/legacy_bats/Grind TGS.bat.legacy"` reports `text: unset`.

### 14.2 Wrapper smoke run (A)

For each wrapper: `cmd /c call "<bat>" < NUL` with `TGS_DRY_RUN=1` set. The printed plan equals `--plan` and the exit code is 0. Nothing runs and no lock is taken.

### 14.3 Settings defaults test (D)

`python tgs-viz\tools\tests\test_settings_defaults.py` imports each refactored module and compares the new values with the literals at `ef23800` (hard-coded in the test):
- statsplus_token `LEAGUES` and TEMPLATE bytes; pull_report `LEAGUES`/`SLUGS`; ratings_db `LEAGUES`; statsplus_history `SLUGS`/`FIRST_KNOWN`/`PROBE_YEARS`; metadata_inputs `SLUGS`; growth_lenses `LEAGUE_SLUG`; parks `LEAGUES[*]["home"]`; `winsim.PROTECTED`; cleanup_clones `ALLOW` for TGS and BLM.
- draft/r5/iafa `DEFAULT_CSV`: `os.path.normcase(os.path.normpath(...))` equal to today's paths.
- `settings.saved_games_raw("26") == "C:/OOTP 26/data/saved_games"`; `saved_games_raw("27") == os.environ["USERPROFILE"] + "/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games"`.
- `ootp_profiles()` equals `ootp/leagues.json` when there is no local file.
- refresh.py and draft.py: `--calib` absent gives calib = league (argument parsing test).
- statsplus `_lev_for` and `drop_foreign` give today's answers for TGS and BLM rows (small fixtures).
- A local file that adds online league `XY` with slug `xyleague`: TEMPLATE gains the line `XYLEAGUE=`, `token_line` is `XYLEAGUE=`, and `--have XY` reads that line.
- A local file with `{"leagues": {"TGS": {"enabled": false}}}`: `winsim.PROTECTED` still holds `thegrandestsalami`; cleanup_clones' skip set holds every settings save and every profile master.
- DEV manifest: `new_league.py register-manifest --league DEV --manifest <copy of leagues.json>` leaves the copy byte-identical, CRLF included.
- `extract_data.upsert_manifest` with an unchanged entry list leaves a copy of leagues.json byte-identical (the atomic write keeps CRLF).
- `ratings_db.connect` guard: with `RATINGS_ARCHIVE_ROOT` at a temp folder holding `vintages/X/_pulls.csv` and no database, `connect()` raises SystemExit and creates no file; with `RATINGS_DB_ALLOW_NEW=1` it creates the database.
- `statsplus_token.token_age` leaves the seen file's bytes and mtime unchanged.
- The Python side of `tgs-viz/control/test/fixtures/python_main_cases.json` (B's file; the test skips with a message when it is missing).
- Run under both interpreters: `python ...` and `py -3.14 ...`.

### 14.4 App-level proof (integration, 16)

- All four leagues load on the test port with the worktree's data; switching keeps the saved league.
- No new npm packages: `git diff ef23800 -- tgs-viz/package-lock.json` is empty; `git diff ef23800 -- tgs-viz/package.json` shows only the removed `extract` line.
- A data write does not reload the page (16, step 6).
- Control failures cannot stop the app (16, step 9).
- Final check on port 3000 only with the user's go-ahead (16, step 13).

---

## 15. Test plans per implementer

Each implementer ends with a report: files changed, commands run, their output (trimmed), anything not done and why. Every dev server in these plans sets `TGS_VITE_CACHE_DIR` (rule 1.5).

### 15.1 A

1. `python tgs-viz\tools\tests\test_bat_equivalence.py` (14.1).
2. `python -m unittest discover -s tgs-viz\tools\tests -p "test_run_task.py"`, with `TGS_CONTROL_DIR` set to a temp dir and `TGS_SELFTEST=1`. Covers:
   - locks: two processes race to take the same lock 50 times and exactly one wins each round; a reader never sees an empty or partial lock file; a lock file holding this test's own pid with a wrong `pid_started` reads as gone (pid reuse) and is reaped; `os.kill` is never called (patch it to raise);
   - stale jobs: an active entry for a dead runner with a running state becomes `lost`; one with no state.json becomes `failed` with the runner.log tail; `--reap` and `--lock-status` print the documented JSON;
   - `--kill` on a running `selftest.long` runner: the runner and its child are gone within 5 s, state `killed`, locks released, active entry removed;
   - named locks: a second `selftest.long` is refused (exit 3, `task.` lock); `selftest.phase` holds `ootp` and a second OOTP-style task is refused; `selftest.ok` starts and finishes during `selftest.phase` step 1; with `selftest.long` holding the data lock, `selftest.phase` step 2 waits and then runs; a job-mode `selftest.ok` started while `selftest.long` runs is `queued` and then `done`;
   - console data-lock question: with `selftest.long` holding the data lock, console `selftest.ok` with stdin `C\n` exits 3, with `R\n` runs with `data_lock: "skipped"`, with stdin at EOF waits and then runs;
   - Ctrl+C: console `selftest.long` started in a new process group; send `CTRL_BREAK_EVENT` during step 1; stdin `Y\n` gives exit 130 and status `stopped`; stdin `N\n` judges step 1 failed under its `fail` policy and ends `failed`;
   - early death: with `TGS_RUN_TASK_TEST_CRASH=1`, run_task raises right after it writes `starting`; the job ends `failed` with a message, its locks and active entry are gone, and it is never stuck on `starting`;
   - archive check: `RATINGS_ARCHIVE_ROOT` at a temp folder with `vintages/X/_pulls.csv` and no database: `selftest.archive` ends `invalid` with `fix_task` `restore_ratings_db`; with `RATINGS_DB_ALLOW_NEW=1` it runs;
   - job mode on every selftest task through `run_task.py --job <dir>` (a test writes request.json): final status, FAILS, steps, events order, `seq` without gaps;
   - `--launch`: starts a runner whose pid differs from the launcher's, then exits 0;
   - prompts: write answer.json for `selftest.confirm` (yes and no), `selftest.gate` (Continue and Stop); `selftest.confirm_zero` asks nothing; `selftest.excel` with `~$a.xlsx` present opens the gate, Continue with the file still there asks again, removing it and pressing Continue goes on;
   - stop `after_step` on `selftest.long`; `after_cycle` on `selftest.loop`; `kill` (child gone within 2 s, status `killed`); stop during the `selftest.hands_off` countdown ends `stopped` before its step;
   - rollback: `selftest.rollback` stopped in step 2 writes its marker; finishing normally writes none;
   - live-refresh claims: `selftest.leagues` emits `league_done TGS` after step 2 and `league_done BLM` after step 3, and `pending_leagues` matches at each step end;
   - secrets: after `selftest.secret`, no file in the job folder contains the secret (byte search), and the log shows `****` both where it was printed whole and where it was split over two writes; `TGS_SECRET_token` set in lower case still reaches the step; an undeclared `TGS_SECRET_OTHER` is dropped with a warning that does not contain its value;
   - `selftest.stdin` exits 0;
   - console mode with `TGS_DRY_RUN=1` takes no lock;
   - conditions: every case in `fixtures/conditions_cases.json` (A owns it; C's test reads the same file).
3. `python tgs-viz\tools\tests\test_catalog.py`: `--list-json` parses, every task has the 3.3 fields, ids are unique, hidden tasks are present with `flags.hidden`, it runs in under 2 s, and it leaves no `StatsPlus Tokens.txt` behind when none existed (point `STATSPLUS_TOKEN_FILE` at a temp path). With `TGS_SETTINGS_LOCAL` at a file holding `{bad`, it exits 0 and lists only `doctor`, with `state.settings_error` set.
4. Wrapper smoke run (14.2).
5. `git diff --stat` shows only A's files.
Until D delivers `settings.py`, A may use a test double placed only in the temp test folder (never at `tgs-viz/tools/settings.py`).

### 15.2 B

1. `node --check` on every file in `tgs-viz/control/`.
2. `node tgs-viz/control/test/fileMap.test.mjs`: every row of 9.2, Windows and POSIX separators, `BLM - Copy` ignored, `.bak-*`/`.tmp` ignored, DEV age_curve gives league null.
3. `node tgs-viz/control/test/guards.test.mjs`: loopback, Host with the request's port, Origin exact match (a `localhost:5173` origin fails), missing Origin with `Sec-Fetch-Site: cross-site` fails, token, content type, job id pattern (`..`, `a/b`, a missing date part all fail).
4. `node tgs-viz/control/test/pythonMain.test.mjs`: every case in `fixtures/python_main_cases.json`.
5. Dev server: from `tgs-viz` in the worktree, `TGS_SELFTEST=1`, `TGS_CONTROL_DIR=<worktree>\.control-b`, `TGS_VITE_CACHE_DIR=<worktree>\.vite-cache-b`, `npx vite --port 3101 --strictPort` (no `--open`). Then `node tgs-viz/control/test/api.smoke.mjs 3101`, which:
   - reads the Vite ws token from `/@vite/client`, opens the Vite websocket with Node's global `WebSocket`, sends `tgs:hello`, gets `tgs:token`;
   - checks 401 without the token and 403 with `Origin: http://localhost:5173`;
   - GET ping, catalog (hidden tasks present), config, jobs/active;
   - runs `selftest.ok` and reads its SSE stream to `done`; runs `selftest.confirm` and answers; `selftest.long` with stop `after_step`; `selftest.long` with `kill`;
   - locks: a second `selftest.long` POST while one runs gives 409 `conflict`; `selftest.ok` while `selftest.long` runs gives 201 with status `queued`; a third non-read-only POST then gives 409 `queue_full`; a read-only task (`doctor`) still gives 201 while both jobs are active;
   - validation: a secret of 5 characters, an undeclared secret name and a secret with a newline each give 400 `bad_secret`; `/new-league/options?type=x` and `?version=2a` give 400 `bad_query`; `/jobs/..%2F..` gives 404;
   - runs `selftest.touch` and receives exactly one `tgs:data` `{league: "TGS", keys: ["players"], reason: "league_done"}`;
   - with no job running, rewrites `public/data/TGS/r5.json` with the same bytes and receives `tgs:data` with `reason: "watch"` within 4 s;
   - settings: a patch with `python.main: ["C:\\nope\\python.exe"]` gives 400 `bad_interpreter` and saves nothing; `reset-local` against a scratch `TGS_SETTINGS_LOCAL` renames it.
6. Vite output during step 5 shows no `page reload` and no `hmr update /src/index.css` line for data files (start the server with `--debug hmr` once to confirm `[no modules matched]`).
7. `node tgs-viz/control/test/restart.smoke.mjs 3101`: start `selftest.long`, touch `vite.config.js` (an mtime change only), wait for the restart, check the job still runs (heartbeat moves), GET jobs/active returns it, SSE resumes from the last cursor, and `ping.debug.instances_alive` is 1 (with `TGS_SELFTEST=1`, ping adds `debug: {instances_alive, timers}`). Then stop the Vite process itself and check the job still runs; start Vite again and repeat the check.
8. Tailwind: before and after the index.css change, fetch the compiled CSS for `src/index.css` from the dev server and list the class selectors. Report the removed ones and show none of them appears in `src/` (grep). Expected: only classes that came from data JSON strings disappear.
9. `node tgs-viz/control/test/failsafe.smoke.mjs`: starts Vite on 3101 five times, once per case, and each time checks that `/data/leagues.json`, `/data/TGS/hitters.json`, `/data/BLM/pitchers.json`, `/data/RG/hitters.json` and `/data/DEV/rating_trends.json` answer 200 with JSON, that `/` serves the app, and that Vite printed at most one `[tgs-control]` line per cause. Cases: `TGS_SETTINGS_LOCAL` at a file holding `{bad`; `TGS_CONTROL_DIR` at a folder that does not exist; `TGS_SETTINGS_LOCAL` at a file whose `python.main` is `["C:\\nope\\python.exe"]` (then also POST a selftest job: 500 `python_failed`, and Vite keeps serving); `TGS_CONTROL_TEST_THROW=import` (plugin.js throws while it loads: `ping` answers `control.on: false`); `TGS_CONTROL_TEST_THROW=configure` (it throws inside `configureServer`: same).
10. `git diff --stat` shows only B's files; the package.json diff is the one `extract` line.

### 15.3 C

1. `node tgs-viz/tests/client/softMerge.test.mjs` (`keysToFetch` for both park modes, the `_park` draft fallback, an unused file fetching nothing, `null` meaning everything; `mergeRaw` keeping a failed key's old value) and `inputConditions.test.mjs` (every case in A's `tgs-viz/tools/tests/fixtures/conditions_cases.json`, skipping with a message when the file is missing; the Get Ratings cookie cases for the four token states; `startConflict` for conflict, queue_full, waits and free).
2. Dev server on 3102 (`TGS_SELFTEST=1`, `TGS_CONTROL_DIR=<worktree>\.control-c`, `TGS_VITE_CACHE_DIR=<worktree>\.vite-cache-c`) and the preview browser:
   - each of TGS, BLM, RG, DEV loads; switch leagues and park basis; reload keeps the league;
   - `/control` shows the cards, no hidden task; run `selftest.ok`, `selftest.confirm`, `selftest.gate`, `selftest.long` (Stop, then Kill with the dialog), `selftest.secret` (field is a password field, a 5-character value is refused in the browser, log shows `****`), `selftest.hands_off` (the countdown shows);
   - two jobs: start `selftest.long`, then `selftest.ok`: two panels, the second says "Waiting for Self test long to finish.", Cancel works; start `selftest.long` again: its Start is disabled with the reason;
   - switch league while `selftest.long` runs: the job panels reattach and the log continues;
   - live refresh: on `/hitters` for TGS, sort by a column, filter, open a player card, then run `selftest.touch` (file `TGS/hitters.json`): no LoadingScreen, sort and filter kept, card still open on the same player, footer shows `Updated HH:MM`. `performance.timeOrigin` read in the page before and after is unchanged (no page load happened). Repeat the open-card check on `/draft-board`, `/mock-draft`, `/optimizer` and `/market-value`;
   - keep old data: on RG, run `selftest.corrupt`: no ErrorScreen, footer shows the failure line, the next update recovers;
   - ErrorScreen: in the worktree only, add a temporary entry `{"id": "ZZT", "name": "ZZT"}` to `tgs-viz/public/data/leagues.json`, pick ZZT: the sidebar stays, the message has no `extract_data.py`, pick TGS and it loads. Restore with `git checkout -- tgs-viz/public/data/leagues.json`.
   - NewLeagueWizard: each type renders its fields and shows server validation errors (type `local_export` with a missing save, bad id `tgs`, id `CON`); a save cannot be typed; do not start a creation job here.
   - Setup page renders the Python line and the doctor rows; with a scratch `TGS_SETTINGS_LOCAL` holding `{bad`, the page shows the settings error and Reset local settings works.
   - Default org: with a scratch local file that sets `my_org` for TGS to another org, the Org Builder opens on that org once the config arrives.
3. No console errors in the browser during the above.
4. `git diff --stat` shows only C's files; `git status` shows no tracked data file changed.

### 15.4 D

1. `python tgs-viz\tools\tests\test_settings_defaults.py` and `py -3.14 tgs-viz\tools\tests\test_settings_defaults.py` (14.3).
2. `python -m py_compile` on every modified Python file; `python tgs-viz\ingest\ratings.py --selftest`.
3. `python tgs-viz\tools\settings.py validate`; `--json`; `--app-json`; a `set --patch-file` round trip against `TGS_SETTINGS_LOCAL=<temp>`.
4. `python tgs-viz\tools\tests\test_new_league.py` with `TGS_SETTINGS_LOCAL`, a temp control dir and `RATINGS_ARCHIVE_ROOT` at a temp archive: `check` for each type with good and bad fields (device-name ids, a typed save not in `options`, a reused id with archive rows, a clone prefix that matches an existing save); `--precheck-out` writes the file only when asked; `profile` writes `pending: true` and `register` removes it; `register`, `register-manifest`, `remove` and `rollback` against a temp copy of leagues.json (`--manifest`); `rollback` after a fake first pull deletes the id's archive rows and moves its vintages folder, and a second `rollback` changes nothing; `token --league` with `STATSPLUS_TOKEN_FILE` at a temp file writes the slug line.
5. `refresh.py` `write_json`: writing to a temp path keeps the `.bak-` copy, leaves no `.tmp`, and gives the same bytes as the old code.
6. One real end-to-end run in the worktree only, type `local_export`, id `RGT`, save `Regular Game` (read-only use of the user's OOTP CSV export), with `TGS_SETTINGS_LOCAL` pointing at a scratch file and `RATINGS_DB_ALLOW_NEW=1` (the worktree has no ratings archive; run_task's archive check honors the same variable), through `run_task.py new_league --input ...` once A's runner exists, else step by step by hand. Expect `partial`: the worktree has no trained ML models (gitignored), so the ML steps fail. Then clean up by moving these into the scratch folder: `tgs-viz/public/data/RGT`, `tgs-viz/backtest/vintages/RGT`, the worktree-only `tgs-viz/backtest/ratings_history.db*` the run created, `tgs-viz/ingest/.cache/history/export_rgt_*.json`; remove the RGT entry with `remove_manifest_entry`; restore any tracked file the run rewrote (for example `tgs-viz/backtest/vintages/_schema.sql`) with `git checkout -- <file>`, in the worktree only. `git status` must be clean except D's own files.
7. `python tgs-viz\tools\doctor.py` and `--json` on this PC; paste the output. With `STATSPLUS_TOKEN_FILE` pointed at a temp file holding a fake 36-character token, the output never contains it, and the seen file is not written. With `TGS_JOB_ID` set to an active selftest job's id, the `jobs` row does not count it.
8. `python ootp\cleanup_clones.py --league TGS --junk --dry-run` (lists, deletes nothing, exits 0). Do not run without `--dry-run`.
9. `python ootp\winsim.py --reset-input` exits 0 within a second and opens no window. Run it only while the user is not using the mouse.
10. `git diff --stat` shows only D's files.

---

## 16. Integration test plan (after A, B, C and D report)

Run in the worktree, port 3100, `TGS_SELFTEST=1`, default control dir, `TGS_VITE_CACHE_DIR=<worktree>\.vite-cache-int`, `TGS_SETTINGS_LOCAL` pointing at a scratch file (the Vite process and every job it spawns share it).

1. Re-run every implementer's automated tests (15.1-15.4, steps that need no browser).
2. `python tgs-viz\tools\run_task.py --list-json` lists the 18 bat tasks, `update.TGS`, `update.BLM`, `update.RG`, `update.DEV`, every task in 4.6 (`new_league` and `new_league_cleanup` with `flags.hidden`; `restore_ratings_db` hidden only when the worktree has an archive): 41 tasks, plus the selftests.
3. Start Vite on 3100. Open `/control/setup`: every check is ok or a known warning (the worktree has no ratings archive and no ML models).
4. From the page, run the safe real tasks: `pull_report`, `sim_tgs_preview`, `sim_blm_preview`, `winsim_games`, `doctor`. Each ends `done` or "Finished with problems" with the expected output.
5. Run `selftest.*` once each from the page.
6. Live refresh without reload: page on `/hitters` (TGS) with a sort and an open card, record `performance.timeOrigin`; run `selftest.touch`; the table updates, `performance.timeOrigin` is unchanged, the Vite terminal shows no page reload.
7. Locks across modes: (a) start `selftest.long` from the page; in a console with `TGS_SELFTEST=1`, `python tgs-viz\tools\run_task.py selftest.long` refuses with exit 3 and the "is this same task" message; (b) `python tgs-viz\tools\run_task.py selftest.ok` asks W/R/C; C exits 3; (c) stop the job; start `selftest.phase` from the page; during its step 1 start `selftest.ok` from the page: it runs at once; start `selftest.long`: `selftest.phase` step 2 waits with "Waiting for ..." and runs after it; (d) `cmd /c call "Bank Season.bat" < NUL` with `TGS_DRY_RUN=1` prints its plan and exits 0 (dry runs take no lock). Stop every job.
8. Restart and window survival: start `selftest.long`, touch `vite.config.js`, the page reloads, the Control page shows the job still running, the log continues. Then start a second Vite on 3100 in its own visible console window (`start "TGS 3100" cmd /k` with the same variables), start `selftest.long` from its page, and close that console window with its X button (computer use, or ask the user). The job's heartbeat keeps moving; start Vite again and the job reattaches.
9. Failsafe: re-run B's `failsafe.smoke.mjs` on 3100.
10. Fresh-clone flow (the worktree has no ratings archive, like a GitHub clone): run `new_league` for type `local_export`, id `RGT` (as 15.4 step 6) without `RATINGS_DB_ALLOW_NEW`: it ends `invalid` with the Rebuild ratings archive button. Press it: `restore_ratings_db` builds the worktree's archive from the tracked vintages. Run the New League again: the league appears in the picker without a reload, `update.RGT` and `remove_league.RGT` appear in the cards, RGT loads. Run `remove_league.RGT`. Then clean up as in 15.4 step 6, also moving the worktree's restored `ratings_history.db*` into the scratch folder, and confirm `git status` is clean.
11. OOTP from a page job, only with the user present and OOTP 26 open: run `ootp_check_26` from the page. OOTP comes to the front, `ootp/winsim_grab.png` is written, nothing is clicked. This is the first proof that a detached job can bring OOTP forward. Delete the png afterwards (it is untracked).
12. Kill reset, only with the user present and hands off the mouse: start `selftest.hands_off`, then Kill now during its step; the log shows the `--reset-input` call and its result.
13. Only with the user's explicit go-ahead, and when they are not using the app: close every bat window first (a looping Grind reads its .bat from disk by byte offset, Grind TGS.bat:66, and would run fragments of the new wrapper), stop every job, close their running app. Merge `control-panel` into `main` in the user's checkout. Double-click `Launch TGS.bat`. Check: the app opens on `http://localhost:3000`, the saved league is selected, TGS, BLM, RG and DEV each load, the Control page shows the tasks, `pull_report` runs from the page, and `old bats (backup)` is there. Run no other task.

---

## 17. Critic traps: where each is handled

| Critic item | Handled in |
|---|---|
| 1 No new npm packages | 1.3, 14.4 |
| 2 Port 3000 and localStorage | 5, 6.6 (`--strictPort`), 8.3 (the request's port), 16.13 |
| 3 ErrorScreen trap | 10.1 (sidebar kept), 12.3 (manifest after data), 9.4 (keep old data) |
| 4 Destructive `extract_data.py` advice | 1.12, 10.1, 2 (B removes the `extract` script) |
| 5 Job lifetime and pipes | 8.7 and 6.1 (`--launch`: detached, breaks away from job objects, log file), 7.3 (stop between steps, kill only on request, atomic refresh.py writes 11.4), 1.9, 16.8 |
| 6 Secret ignore rules | Already committed in `1b82cf6` (.gitignore has `StatsPlus Tokens.txt`); doctor `git_ignore` check (13.1) |
| 7 Prompts | 6.3 preview then confirm; 11.15, 11.19, 11.20 EOF guards |
| 8 winsim never starts OOTP | 10.3 kill dialog text; 7.3 `--reset-input` after a kill |
| 9 Protected saves and DEV | 11.14 |
| 10 Bank Dev Seasons skips RG | 4.3 bank_dev reminder line (the bat's steps stay exact); 4.6 `dev_rescore` and `retrain_ml`; user decision 19 |
| 11 Missing jobs and writers | 4.6 `bank_market_fit`; `metadata.json` noted, no writer offered |
| 12 Online league needs engine changes | 11.4, 11.5, 11.8, 12 |
| 13 `--manifest-only` vs contracts | the `data` lock (7.5) keeps it away from a pull; new tasks use `register-manifest` (4.5) |
| 14 LF bats | 1.11, `.gitattributes`, 14.1 wrapper and backup checks, batsim reads LF and CRLF |
| 15 ESM | 1.10 |
| 16 Home team in park_blend.json | 11.13 plus the `parks_update` task |
| 17 BLM default org vs park home | 3.2 `my_team` and `my_org` |
| 18 Workbooks carry the team | Out of scope (11) |
| 19 LEAGUE_TEAMS readers | Unchanged; unknown leagues already fall back to null |
| 20 archived_clones.txt vs ignored CSVs | Out of scope (later GitHub phase) |
| 21 Excel lock files | 13.4 |
| 22 History runtime label | 4.3 get_history time, 6.5 rule 5 |
| 23 metadata_inputs months | 4.3 recalibrate_blm description |
| 24 LFS | Do not touch LFS or rewrite history |
| 25 Line endings of tracked files | Only `*.bat` gets an eol rule, and `*.bat.legacy` is marked `-text` so the fixtures keep their bytes. Do not run `git add --renormalize` |

---

## 18. Out of scope for this build

- README rewrite and `WHICH BUTTON.docx` (decision 9): a later phase, after integration.
- The app reading the manifest `basis` for pricing (leagueCalib.js:163 falls back to TGS for RG). Changing it would move RG's numbers.
- Converting the remaining in-place writers (dev_signals.py:1120-1121, agecurve_fit.py:360-361 and others) to atomic writes. refresh.py, whose hitters and pitchers files decide whether a league loads at all, is converted (11.4). The hold-and-flush rules (9.3) and the keep-old-data rule cover the rest.
- Hiding a disabled league from the app's league menu. Disabling only hides its tasks; the menu follows leagues.json, as today.
- Web Worker parsing of the large JSON files.

---

## 19. Decisions for the user

Each has a default that the build follows. The integrator asks only these:

1. Bank Dev Seasons and RG. Default: the bat stays exact (TGS and BLM only) and prints "Regular Game still uses its old dev numbers. Run Update Regular Game to refresh them." If the user wants Bank Dev Seasons to rescore RG itself (and any later league that borrows TGS or BLM), A adds three `collect` steps per such league after the BLM score step, each under a visible echo header ` --- RG dev signals and ML scores (new in the app version) ---`, and the reminder line goes away.
2. Live checks that need the user present (16, steps 11 to 13): the OOTP focus check with OOTP 26 open, the kill-reset check, and merge day, which also needs every bat window closed first.

---

## 20. Objections not taken

Everything else from both reviews is folded into the sections above. These were taken in part, or in another form, or not at all:

1. User setup 1, "on any error, turn Control off": only a failure while Control starts (the import or `configureServer`) turns it off. A request that fails answers 500 and Control stays on, so one bad state.json read cannot hide the page (8.10).
2. User setup 3, "refuse only when both tasks drive OOTP or it is the same task": the lock set is wider. Tasks that delete or create the same clone saves, or read a dump folder OOTP is writing, also refuse, because `cleanup_clones --junk` deletes clones the running sim has not reached yet (4.10, 7.5).
3. User setup 3, "ask Run anyway?": console mode asks Wait / Run anyway / Cancel. Page jobs never run anyway; they queue, because two page jobs writing one league at once is the case live refresh cannot make consistent.
4. Works-and-safe 17, "endless tasks release the global lock during winsim and hold an ootp lock": taken in a general form (named locks, 7.5), not as a special case for endless tasks.
5. User setup 8 and works-and-safe, "use cmd's signed errorlevel rule in console mode": not taken. A step that ends with a crash or Ctrl+C code counts as failed. The old rule silently counted a crashed step as a success; the difference is written down (6.4, 14.1 difference 2).
6. User setup 7, "ask the user before building": built with the safe default (the bat stays exact, plus a reminder line) and listed in section 19, so the build does not wait on the answer.
7. User setup 5, "four pages hold the row": MarketValuePage already finds the row again by ID (MarketValuePage.jsx:83-86). It moves to the shared hook anyway, so all six pages follow one rule.
8. Works-and-safe 1, "load the plugin inside try/catch (dynamic import)": taken, with one change. A dynamic import with a literal path is still bundled into the config by esbuild, so it would not catch a syntax error. The import uses a computed URL that esbuild leaves alone (8.1).
9. Works-and-safe 4, "or run the restore as step 0": not taken. The task refuses and offers a Run button, so rebuilding the archive stays a step the user sees and chooses.
10. Works-and-safe 10, "mask only secrets of 8 or more characters": replaced. Non-blank secrets under 8 characters are refused at input, so no secret is ever left unmasked in a log.
11. Works-and-safe 19, "clear the timers in buildEnd": the instance is disposed on the old server's `close` event and again at the next `configureServer`. That covers both restart paths without relying on hook order.
12. Works-and-safe 25, "TaskForm requests catalog?refresh=1": not needed. B stats the catalog's watched files on every catalog request and every 5 s (3.4).
13. Works-and-safe 26, Excel check in console mode: not taken. Console mode stays identical to the bats, where the sheet write already fails loudly. Job mode checks and waits (7.3).
14. Works-and-safe 27, "keep runnable copies in `_legacy/`": taken, in a folder named `old bats (backup)` so the user can find it (6.7).
