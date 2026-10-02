# Perfekt Projections

A baseball analytics platform for competitive **Out of the Park Baseball** (OOTP) leagues. It has
three parts: a projection engine calibrated on hundreds of simulated seasons (about 360 for TGS
and 77 for BLM), a data pipeline from each league's StatsPlus site, and a React app that turns
about 13,000 to 16,500 players per league into roster, draft and organization decisions.

It is built for and used in two online leagues with 30 human GMs each. Everything runs on one
Windows PC. `Launch TGS.bat` starts the app, and the app's **Control** page runs every job.

![Mock Draft](docs/screenshots/mock-draft.png)

**Contents:** [What it does](#what-it-does) ·
[First-run setup](#first-run-setup) ·
[The Control panel](#the-control-panel) ·
[Jobs](#jobs) ·
[Add a league](#add-a-league) ·
[StatsPlus tokens and history](#statsplus-tokens-and-history) ·
[Live data refresh](#live-data-refresh) ·
[Dev signals and the DEV league](#dev-signals-and-the-dev-research-league) ·
[The ML dev model](#the-ml-dev-model) ·
[The pricing engine](#the-pricing-engine) ·
[How it fits together](#how-it-fits-together) ·
[Repository layout](#repository-layout) ·
[Tests](#tests)

---

## What it does

**Roster Optimizer** builds the best 26-man roster from any pool. It picks two platoon lineups
(against right- and left-handed pitching, weighted by the league's measured plate-appearance
share), a 5-man rotation, an 8-man bullpen and a bench (backup C, utility IF, utility OF, flex).
It can score the roster with linear, Pythagorean, Monte Carlo and durability-adjusted win models.

![Roster Optimizer](docs/screenshots/optimizer.png)

**Organization Builder** places every player in a 30-club organization at the level he should be
at, from MLB down to Rookie ball, plus a Winter League overlay. A player moves up when he would
rank in the top third at the next level. He moves down only when he falls below the bottom third of
his own. Minors playing time goes first to the players with a real chance to reach the majors
(MLB %, below). It enforces staffing minimums, roster caps and a real backup catcher on every
affiliate, and it names the filler to sign when the system runs out of bodies.

![Organization Builder](docs/screenshots/organization.png)

**Team Projections** projects every club's optimized roster to a win total. The totals are
zero-sum across the league, so the standings add up.

![Team Projections](docs/screenshots/standings.png)

**Draft tools.** The Draft Board ranks a class by age-relative percentile, ceiling and projected
peak, with flags for durability, work ethic and intelligence. The Mock Draft slots the whole class
and shows where each drafted player actually went. Two-way threats are flagged when both the bat
and the arm project above league average. Both boards exist on the neutral park basis and on your
home-park basis, so you draft for the park you play in. The app also has International (IAFA),
Rule 5 and Free Agency lists. The Free Agency pages (hitters and pitchers) exist for every player
league, not only TGS.

**Rating Trends** keeps an archive of every ratings pull. It shows the biggest risers and fallers
and a measured development curve, split by work ethic, intelligence and leadership.

![Rating Trends](docs/screenshots/trends.png)

**Market Value** fits a $/WAR market to the league's own free-agent signings, with contract
control windows and trade value.

![Market Value](docs/screenshots/market-value.png)

**Team sheets** score every hitter and pitcher on current and potential value. The raw projected
stat lines behind each number are one click away. Each player card also shows his dev signals, his
ML development odds and a year-by-year WAA path.

![Hitters](docs/screenshots/hitters.png)

**Other pages:** Waivers & DFA, Parks, Series Planner (one locked lineup against right-handers and
one against left-handers per series, for online leagues), Dev Analysis, Make-it odds (DEV league
odds tables by age, rating and attribute), Model vs Actual (each fitted layer against the sims) and
**Control** (runs every job, below).

---

## First-run setup

You need a Windows PC. OOTP is needed only for the sim tasks, local OOTP saves and the OOTP
exports (draft pool, Rule 5, international class).

| What | Version | Used for |
|---|---|---|
| Python, the main command (`python`) | 3.11 or newer (3.13 recommended) | Every task |
| Python, the ML command (`py -3.14`) | Python 3.14 through the `py` launcher | ML dev scores and retraining. Optional |
| Node.js | 20.19 or newer on 20.x, or 22.12 or newer (Vite 7). Node 22 LTS recommended | The app |
| OOTP 26 | | TGS clone sims and its OOTP exports |
| OOTP 27 | | BLM clone sims, the Regular Game save, the DEV research league |
| Excel | | Only the BLM SP/RP paste and the TGS metadata workbook |

The project uses two Python interpreters on purpose. `python` runs the pipeline. `py -3.14` runs
the machine-learning scripts, which need pandas, scikit-learn and XGBoost. You can point either
command at another install on the Setup page.

### Step by step

1. **Get the code.**
   ```
   git clone https://github.com/perfektoa/perfektprojections.git
   ```
   The repo ships the app data for four leagues (TGS, BLM, Regular Game, DEV), so the app runs
   without any league access.

2. **Install Python** from python.org and tick **Add python.exe to PATH**. Then, from the repo
   folder:
   ```
   python -m pip install -r requirements.txt
   ```
   The last four packages in that file (pyautogui, pywin32, opencv-python, Pillow) are only for
   the tasks that drive OOTP.

3. **Optional: install Python 3.14 for the ML.** Then:
   ```
   py -3.14 -m pip install -r requirements-ml.txt
   ```
   Without it the ML score steps fail, and after the next pull the app shows the older cell-method
   dev numbers instead of the ML ones.

4. **Install Node.js 22 LTS** from nodejs.org. Then install the app's packages once:
   ```
   cd tgs-viz
   npm install
   ```
   `Launch TGS.bat` never runs `npm install` for you.

5. **Run `Check Setup.bat`.** It checks Python, both sets of packages, Node, the app packages, the
   settings, the StatsPlus tokens, the OOTP folders and saves, each league's data, the ratings
   archive and the ML models. It changes nothing and needs no internet. It fails only when the app
   cannot work (Node, the app packages, the settings files, or a league whose data cannot load).
   On a fresh clone, expect warnings: no tokens, no ratings archive, no ML models, and OOTP saves
   that belong to the author's leagues.

6. **Run `Launch TGS.bat`.** The app opens at http://localhost:3000. Leave the window open: it is
   the app's server. If it says port 3000 is in use, the app is probably already running in
   another window.

7. **Rebuild the ratings archive.** In the app, open **Control**, then **Setup check**, and run
   **Rebuild ratings archive**. It rebuilds `tgs-viz/backtest/ratings_history.db` from the saved
   vintages in the repo. From a terminal: `python tgs-viz\backtest\vintage_backup.py --restore`.
   Every task that reads the archive refuses to run until it exists: Get StatsPlus Ratings, Get
   StatsPlus History, the league Update cards, Update park factors, Grind, Recalibrate, Sim Dev
   League, Bank Dev Seasons, the Retrain and Rescore cards, and the New league wizard.

8. **Make it yours** on the Setup check tab. Turn off the leagues you do not play in, set your
   OOTP saved_games folders, your team (the park home club) and your org (the org the Org Builder
   and Waivers pages open on). The page saves to `settings.local.json` in the repo folder. That
   file stays on your PC (it is in `.gitignore`).

9. **Add your own league** with the **New league** tab ([below](#add-a-league)). For an online
   league, put its StatsPlus token in `StatsPlus Tokens.txt` first
   ([below](#statsplus-tokens-and-history)).

The TGS and BLM entries in the committed settings are the author's private online leagues. You
can pull them only with a team and a token in those leagues.

### Not on GitHub

These are too big or too private for the repo. A fresh clone works without them, with the limits
shown.

| Missing on a fresh clone | Effect | How you get it |
|---|---|---|
| `ratings_history.db` (ratings archive) | Most update tasks refuse | Rebuild ratings archive (step 7) |
| `StatsPlus Tokens.txt` | Online pulls ask for browser cookies | Paste your own tokens |
| ML models (`tgs-viz/backtest/.dev_cache/`) | ML scores fail; the app falls back to the cell method after a pull | Bank Dev Seasons or Retrain, which need a DEV league of your own |
| DEV vintages and dumps | DEV tasks have nothing to read | Run your own DEV research league |
| Clone-sim archive and baseline ratings tables (`tgs-viz/engine/calib/<LG>/*.csv`) | Recalibrate and Grind need them. The app and the update tasks use the shipped fitted constants | Not in the repo |
| `tgs-viz/ingest/.cache/` (cached StatsPlus pulls) | Tasks that rebuild from the cached pull have nothing to read | Run Get StatsPlus Ratings once |

---

## The Control panel

The **Control** link sits at the bottom of the app's menu. The page runs every job in the
project, each the same as its `.bat` file. It has three tabs:

- **Tasks:** one card per job, grouped (Everyday, Your leagues, Season end, Calibration and clone
  sims, DEV research league and ML, OOTP tools, Setup and checks). Groups collapse.
- **New league:** the wizard that adds a league ([below](#add-a-league)).
- **Setup check:** the same check as `Check Setup.bat`, with a Run button next to each problem a
  task can fix. It also holds the settings form, **Reset local settings** and **Replace a
  StatsPlus token**.

### Run a task

1. Press **Run** on a card. Each card says what the task does, how long it takes, and what to
   watch for (for example "Needs internet", "Close Excel on the league's sheets first", or "Takes
   over your mouse and keyboard"). A card that replaces a bat names it, for example "Same as
   Get StatsPlus Ratings.bat".
2. Fill in the form. It shows only the inputs that apply. For example, the cookie fields appear
   only for a league with no saved StatsPlus token.
3. Press **Start**. A job panel opens at the top of the page. It shows each step with a status
   dot, the live log, and the elapsed time.

The job panel asks when a task needs you:

- **Changes to your sheets:** Recalibrate TGS and Sync Metadata show every cell they would
  change, then ask **Apply** or **Skip**. With nothing to change, they do not ask. Grind and
  Recalibrate BLM write without asking (backups are made).
- **Deleting clone saves:** Recalibrate and the Clean up cards list every folder first and ask.
  Grind deletes its spent clones on its own.
- **A mid-run step:** for example the BLM SP/RP paste. Press **Continue** when it is done.
- **Excel is open** on a sheet the task writes: it waits and asks you to close Excel.
- **OOTP tasks:** you tick a box that OOTP is open inside a league. A 5-second "Hands off"
  countdown runs before the first step that clicks. To abort a sim, slam the mouse into a screen
  corner. If OOTP runs as administrator, use the `.bat` with **Run as administrator** instead: the
  app cannot click an OOTP that runs as administrator.

To stop a task, press **Stop after this step** (or **Stop after this cycle** for a Grind). **Kill
now** ends the current step at once; a killed step can leave one half-written file (its `.bak`
copy stays), and OOTP keeps simming until you stop it inside OOTP.

Secrets (tokens and cookies) go in password fields. They never go into the job files or the log;
the log shows `****` in their place. Only **Replace a StatsPlus token** and the New League wizard
save a token, and only to `StatsPlus Tokens.txt`. A secret must be at least 8 characters.

The **Recent runs** list and each job's own page (`/control/jobs/<id>`) keep the log and the
result. Job folders live in `.control/` in the repo folder; the newest 50 finished jobs are kept.

### Running two tasks at once

| Kind of task | Rule |
|---|---|
| Read-only tasks (Data date report, Setup check, the sim previews, Check StatsPlus tokens, List OOTP installs) | Run any time. They take no lock |
| The same task twice | Refused |
| Two tasks that drive OOTP | Never together: they share your mouse |
| Tasks that write app data | Take turns. The second one waits, and its button reads "Start (waits for ...)". Only one task can wait at a time |
| Recalibrate and Clean up clones for a league | Refused while that league's Grind or Sim runs |
| Bank Dev Seasons and Update DEV | Refused while Sim Dev League runs |

A Grind holds the app-data turn only during its few minutes of recalibrate steps per cycle, so Get
StatsPlus Ratings and the other everyday tasks can run while a Grind sims.

### The .bat files still work

Each `.bat` file is now a thin wrapper. It runs the same task through
`tgs-viz/tools/run_task.py` in a console window, asks the same questions in the console, and
respects the same locks. If a page task holds the app-data turn, the console asks: wait, run now
anyway, or cancel. A test checks that every bat still runs the same commands in the same order
with the same exit codes (742 scenarios). The few allowed differences are listed in
`tgs-viz/control/DESIGN.md`, sections 6.5 and 14.1.

If the new runner ever breaks, the folder `old bats (backup)` holds the previous bats. Double-click
the same name there.

When the plugin behind the page cannot start, the app still loads and the Control page says why.
Run `Check Setup.bat` to see what is missing.

---

## Jobs

Every job is a task card on the Control page. "Bat" names the file that runs the same job. Times
come from the task cards.

`Launch TGS.bat` starts the app. `Check Setup.bat` runs the Setup check in a console.

**Everyday**

| Task | Bat | What it does | Time |
|---|---|---|---|
| Get StatsPlus Ratings | `Get StatsPlus Ratings.bat` | Pulls TGS and BLM ratings, then rebuilds draft boards, Rule 5 pools, age curves, rating trends, dev signals and ML scores. Ends with the data date report | 5 to 15 minutes |
| Update Draft Board | `Update Draft Board.bat` | TGS and BLM draft boards from your OOTP draft-pool export | 1 to 2 minutes |
| Update Dispersal Board | `Update Dispersal Board.bat` | TGS dispersal board: every player in the folding orgs | Under a minute |
| Update international board | | IAFA board from your OOTP export | Under a minute |
| Bank market fit | | Refits each league's market value model | A minute or two |
| Data date report | | The date of the data the app serves, per league | Seconds |

**Your leagues** (one card per enabled league)

| Task | Bat | What it does | Time |
|---|---|---|---|
| Update TGS, Update BLM | | One online league's pull and rebuild | 5 to 10 minutes |
| Update Regular Game | `Update Regular Game.bat` | Reads the Regular Game save's CSV export (OOTP 27), prices it with BLM's calibration, then dev signals and ML scores | 1 to 3 minutes |
| Update and Remove for leagues you add | | Made by the New League wizard | |

**Season end**

| Task | Bat | What it does | Time |
|---|---|---|---|
| Get StatsPlus History | `Get StatsPlus History.bat` | Past rating snapshots for one league into the ratings archive | About an hour per run (5 dates, 15 minutes apart; StatsPlus allows 5 past-date requests a day) |
| Bank Season | `Bank Season.bat` | Saves finished season stats and a dated snapshot of the projections | 1 to 3 minutes |
| Recalibrate BLM | `Recalibrate BLM.bat` | BLM metadata from StatsPlus and your SP/RP paste, then the regressions and the pitching curve per block. Refuses in game months 4 to 9, and stops on a paste from the wrong season | A few minutes plus the paste |
| Sync Metadata | `Sync Metadata.bat` | Copies the metadata constants into the TGS and BLM sheets; shows each change and asks | Under a minute |
| Update park factors | | Rebuilds park factors from your team, then both leagues' app data. Run it after you change your team | A few minutes |

**Calibration and clone sims**

| Task | Bat | What it does | Time |
|---|---|---|---|
| Grind TGS, Grind BLM | `Grind TGS.bat`, `Grind BLM.bat` | Sims clone leagues (10 clones of 10 seasons), recalibrates, deletes spent clones, repeats | About 75 minutes per cycle, until you stop it |
| Recalibrate TGS | `Recalibrate TGS.bat` | Refits TGS constants from the clone sims; you confirm before the sheets change | 1 to 3 minutes |
| Sim TGS | `ootp\4 - Sim TGS.bat` | Clones the TGS Baseline and auto-plays each clone in OOTP 26 | About 75 minutes |
| Sim TGS (preview), Sim BLM (preview) | `ootp\3 - Sim TGS (preview).bat` (TGS) | The sim plan only. Clicks nothing | Seconds |
| Clean up TGS clones, Clean up BLM clones | | Deletes spent clone saves; lists them and asks first | Under a minute |

**DEV research league and ML**

| Task | Bat | What it does | Time |
|---|---|---|---|
| Sim Dev League | `Sim Dev League.bat` | Sims DEV TESTS in OOTP 27, banks the yearly dumps, rebuilds DEV trends | Depends on OOTP |
| Bank Dev Seasons | `Bank Dev Seasons.bat` | Banks hand-simmed DEV seasons, prices DEV with each league's current calibration, rebuilds DEV trends and odds, retrains the ML models, rescores TGS and BLM | Hours; about 13 GB of memory (measured at 295 seasons) |
| Update DEV | | Banks new DEV dumps and rebuilds the trends file. No simming | About 20 seconds per season |
| Retrain the ML dev models (also Retrain the TGS ML models, Retrain the BLM ML models) | | Re-prices DEV for each basis it trains (TGS: `reprice.py`; BLM: the DEV age-curve refit with BLM's calibration, which also rewrites the DEV age curve), rebuilds the dev odds and signals where needed, retrains on every banked DEV season, checks the models, then rescores every league that uses them (BLM's: BLM and Regular Game) | Hours; about 13 GB of memory (measured at 295 seasons) |
| Rescore dev signals and ML | | Reruns dev signals and ML scores with the current models | A few minutes |
| Test DEV loading, Test the DEV year picker | | First-run checks of the DEV sim. They never sim | Under a minute |

**OOTP tools**

| Task | Bat | What it does | Time |
|---|---|---|---|
| Check OOTP (26) | `ootp\1 - Check OOTP (26).bat` | Lists windows and saves a screenshot of OOTP 26. Clicks nothing | Seconds |
| Grab a menu (26) | `ootp\2 - Grab a menu (26).bat` | Screenshot of a menu you open in the next 6 seconds | About 10 seconds |
| Test the year picker (26) | `ootp\TEST year picker.bat` | Tries the year picker in OOTP 26. Never sims | Under a minute |
| List OOTP installs | | The OOTP versions and saved_games folders found on this PC | Seconds |

**Setup and checks**

| Task | Bat | What it does | Time |
|---|---|---|---|
| Setup check | `Check Setup.bat` | Checks Python, Node, packages, settings, tokens, OOTP folders and league data | Under a minute |
| Replace a StatsPlus token | | Saves a new token for one league in `StatsPlus Tokens.txt` | Seconds |
| Check StatsPlus tokens | | Asks StatsPlus whether each saved token still works | Seconds |
| Rebuild ratings archive | | Rebuilds `ratings_history.db` from the saved vintages. Shown only when the archive is missing | A few minutes |

---

## Add a league

The **New league** tab adds a league in four steps: pick a type, fill in the fields, press
**Review**, then **Add the league**. Save names and OOTP versions are dropdowns, so you cannot type
a wrong path.

| Type | For | You give | What you get |
|---|---|---|---|
| Online league on StatsPlus | A league hosted on statsplus.net | The StatsPlus name, which calibration prices it (TGS or BLM), the token (or browser cookies), and optionally its OOTP save, a history start date and foreign league ids to drop | Player pages, draft board, rating trends, dev signals, ML scores, and an Update card |
| Local OOTP save | A save on this PC, like Regular Game | OOTP version, the save, the calibration | The same pages from the save's database CSV export |
| DEV research league | An all-AI OOTP league you sim in place | OOTP version, the save, seasons per run | A Rating Trends page from its yearly dumps, plus Sim and Update cards |
| Calibration clone league | Clone sims from a pristine master save | OOTP version, master save, clone prefix, years and runs | Sim, preview and cleanup cards. No app league; turning the clones into a calibration is manual |

Rules the wizard checks before it starts:

- The id is 2 to 8 capital letters or digits. It cannot be a Windows device name (CON, NUL and so
  on), TGS, BLM, DEV, a league you already have, or an id used before.
- An online league with no saved token needs the token or both browser cookies.
- A local save needs its database CSV export (`<save>.lg/import_export/csv/players.csv`).
- A clone prefix must not match any existing save, because clean-up deletes every save that
  matches the prefix and has no complete dumps.

Known limits the wizard shows: a new online league prices with neutral parks (My Park equals
Neutral), has no Series Planner file, and needs the OOTP draft-pool export for draft boards.
History pulls work only when you give a history start date. A second DEV league still uses DEV's
age curve and ML models.

If the job fails, stops or is killed before the league is registered, it undoes its own changes:
it moves new folders aside (never deletes them) and removes the settings and app entries. If the
PC restarts mid-job, the job page offers **Clean up unfinished league**. A league you added gets a
card that removes it from the app. Removing it moves its data folder aside and keeps its
archive rows, so its id stays used.

---

## StatsPlus tokens and history

**Tokens.** StatsPlus gives each team one API token per league. To get yours, log in on
statsplus.net, open the league, click **Prefs** (top right, next to Logout) and copy the **Current
Token** from the API Token box. A token is 36 characters and expires 90 days after StatsPlus made
it.

Tokens live in `StatsPlus Tokens.txt` in the repo folder, one line per online league, keyed by its
StatsPlus name in capitals:

```
TGS=<the TGS token>
BLM=<the BLM token>
```

The first pull creates the file with empty lines. Open it in Notepad, paste each token after its
`=`, and save. Or use **Replace a StatsPlus token** on the Setup check tab, which shows the exact
line it fills. The file is in `.gitignore` and never goes to GitHub. The Setup check never prints a
token; it says only "present", "empty" or "looks wrong".

- Every StatsPlus request sends the league's token. With tokens saved, Get StatsPlus Ratings
  updates TGS and BLM in one run and asks for nothing.
- A league with no saved token needs your browser cookies (`sessionid` and `csrftoken`). The page
  shows those fields only then.
- When StatsPlus refuses a request (expired token, login needed, too soon), the step stops, says
  why, and writes nothing. The app keeps its last good data.
- The pulls warn when a token is more than 80 days old. **Check StatsPlus tokens** asks StatsPlus
  whether each saved token still works.
- Grind and Recalibrate reuse a saved reply while the league's in-game date has not moved and the
  reply is under 6 hours old, so they do not download the same data again.

**History snapshots.** StatsPlus can return past ratings for a game date. **Get StatsPlus History**
pulls one snapshot every 6 game months, on Jan 1 and Jul 1, for one league per run. TGS history
starts at 2040-08-07, the first date StatsPlus has (the tool reads that from StatsPlus's reply and
skips earlier dates). BLM starts at 2051-01-01. Each snapshot goes into the ratings archive as an
"asof" pull. It feeds the trends, the age curve and the dev signals, and it never changes the
current player values.

StatsPlus limits past-date requests: one every 15 minutes and 5 a day (its replies on 2026-09-30).
The tool waits as long as StatsPlus says and stops cleanly at the daily cap. Run it again the next
day: it skips the dates it already stored, so a full history fills over several days. Before it
stores a date, it checks that the reply is not today's ratings, that the players' ages fit the
date, that it is not a repeat, and that it is the right league.

---

## Live data refresh

The open app updates itself when a task writes new data. You do not need to reload.

- A task's new files reach the page when the task finishes that league. For example, after Get
  StatsPlus Ratings, TGS updates once after its ML scores, then BLM does the same. You never see
  new dev signals next to old ML numbers.
- The page fetches only the files that changed and that the open view uses. Sort, filters, hidden
  columns and the open player card stay as they were, with the new numbers.
- The sidebar footer says **Updating...**, then **Updated** and the time. If a file fails to load,
  it says **Update failed; showing the previous data** and tries again once.
- It also works for the bat files and for files you change by hand: the page updates about 2
  seconds after the writes stop.
- Only the open league refreshes. Other leagues load the new data when you switch to them.
- If live refresh turns itself off, the footer says so. Press F5 after an update then.

---

## Dev signals and the DEV research league

**The DEV league** is a plain OOTP 27 league named "DEV TESTS" with every team run by the AI. It is
simmed in place, year after year. OOTP's yearly CSV dump gives the true ratings of every player
(no scouting error), plus personality, level and playing time. The shipped trends file covers 483
yearly dumps (game years 2026 to 2508).

The pipeline:

1. **Sim Dev League** sims the league in OOTP 27, or you sim it by hand. Sim Dev League and
   **Update DEV** then run steps 2 and 3. **Bank Dev Seasons** runs steps 2 to 6.
2. `dump_vintages.py` turns each yearly dump into a ratings vintage in the archive.
3. `ratings_db.py --export` builds DEV's Rating Trends page.
4. `agecurve_fit.py` measures the age curve from the true ratings (priced with BLM's calibration).
   Growth peaks at about +0.35 WAA a year at ages 20 to 22, is near zero at 27, and turns
   negative at 28. This curve shapes every league's year-by-year WAA path. It drives the whole
   path for a player with no ML numbers, and the years after the ML's five for the rest.
5. `dev_odds.py` and `dev_rating_odds.py` build the odds grids and the Make-it odds page.
6. The ML datasets and models are rebuilt from the same dumps ([below](#the-ml-dev-model)).

Before the first sim, turn on **Export CSV files after each simulated season** in the league's
settings, then run **Test DEV loading** and **Test the DEV year picker**.

**Dev signals** (`dev_signals.py`, per league) compare each young player with DEV players like him.
They appear in the "Dev signals" column group on the player lists and on the player card.

| Column | Meaning |
|---|---|
| Grow/yr | His growth over the last game-year, summed over the core skills (ages 16 to 26) |
| Pot dir | Whether OOTP's Pot grade went up or down |
| MLB %, Starter %, Star %, Exp peak, Peak range | His odds and expected peak. From the ML model when it is current, else from the DEV cell of players with his age, Pot and growth |
| vs listed | Exp peak minus the peak his listed potential ratings give |
| vs typical | His core skills now, in internal points, against the median of his own league's players with his age and Pot. DEV's typical player stands in when that group has fewer than 20 |
| Flag | **keep** (growth at least 4.5 steps for a hitter or 3 for a pitcher, Pot not falling) or **move** (Pot falling, growth at most 2 or 1) |

---

## The ML dev model

The ML model predicts how far each player aged 16 to 26 will develop.

**What the columns mean.** Each chance starts from the player's current WAA. A player already at a
bar (within 0.05 WAA) reads 100%. Star % is never above Starter %, and Starter % is never above
MLB %.

| Column | Meaning |
|---|---|
| MLB % | Chance his peak reaches -1 WAA: an MLB-level player (a 5th starter or bench bat) |
| Starter % | Chance his peak reaches 0 WAA: an average MLB player |
| Star % | Chance his peak reaches +1.5 WAA |
| Exp peak | His current WAA plus the median predicted gain. Peak range is the 25th to 75th percentile |

The same model drives Proj Potential (current plus median gain), the "Year by year" columns (WAA 1,
2, 3 and 5 years out) and the money path behind free-agent pricing.

**How it is trained.**

- Training data: DEV player-seasons. The peak models use ages 16 to 26 where the eventual peak is
  known. The 5-year path uses ages 16 to 38. The live models were fit on 483 seasons (about 3.2
  million hitter rows and 3.5 million pitcher rows). The features are every rating, potential,
  last year's growth, level and current value.
- Models: gradient boosting, one set per role. The five gain quantiles use XGBoost, on an NVIDIA
  GPU when CUDA works, else the CPU. The reach classifiers and the 5-year path use scikit-learn.
  TGS moved its gain models to XGBoost on 2026-10-02; BLM moves at its next retrain.
  - Gain quantiles (10th, 25th, 50th, 75th, 90th percentile), sorted so they never cross. With
    scikit-learn the low marks never learned: every in-org TGS pitcher aged 16 to 26 read +0 at
    his 10th and 25th percentile (2,898 of 2,898). With XGBoost, 406 of them still do.
    Validation loss, old to new: hitters q10 0.134 to 0.099, q25 0.215 to 0.206, q50 0.310 to
    0.301; pitchers q10 0.069 to 0.054, q25 0.173 to 0.110, q50 0.164 to 0.159. The q75 and q90
    models tied.
  - Reach classifiers for each bar (-1, 0, +1.5 WAA) and for becoming a regular (300 PA or 150 BF
    in a later MLB season).
  - A 5-year path: the median and the mean change in WAA 1 to 5 years out, the spread of next
    season's change, and for ages 27 and up the chance he is still in the league next year.
- Chances blend two parts: the reach classifier and the chance the gain quantiles give for that
  bar. On held-out DEV players the average had a lower log loss than the classifier alone on 11 of
  12 targets, and a better AUC on all 12.
- One model set per league basis. TGS models learn from DEV priced with TGS's calibration; BLM
  models from DEV priced with BLM's. A league that borrows a calibration (Regular Game uses BLM's)
  uses that league's models.

**How accurate it is.** These numbers come from held-out DEV players who debuted after the
training seasons. They were measured on earlier, smaller training sets, with the earlier
scikit-learn gain models.

- The ML beat the older cell method on all 14 headline targets for both bases. TGS basis, hitters:
  peak error 0.62 WAA against 1.26; Starter % log loss 0.038 against 0.057; next-season change
  error 0.26 WAA against 0.33.
- By stage (148-season TGS models): when the ML gave a hitter a 50% or better chance to become a
  regular, it came true 68% of the time at the draft, 78% after two years in a system and 84%
  after four or more. AUC rose from 0.86 at the draft to 0.97 after four years. Pitchers: 61%,
  77% and 82%.
- These are DEV results. They were not measured on TGS or BLM themselves.

**Guards.** The app uses a league's ML file only when it comes from the same pull as its dev
signals; otherwise it shows the cell method. Unsigned international amateurs are marked "ML,
outside training range", because DEV has none.

**Cost.** Retraining takes hours and about 13 GB of memory (measured at 295 seasons). It runs
under the ML Python. The gain quantiles train on the GPU when CUDA works. **Bank Dev Seasons**
and the **Retrain** tasks retrain; the Retrain tasks re-price DEV for their basis first.
**Rescore dev signals and ML** only rescores.

---

## The pricing engine

The engine (`tgs-viz/engine/`) turns 20-80 ratings into full stat lines and wins above average
(WAA), separately against right- and left-handed opponents. It is pure Python.

- **Ratings to stat lines.** Each outcome rate (strikeouts, walks, home runs, hits on balls in
  play, extra-base hits and so on) is a function of one rating. The base form is a two-segment
  line with its kink at rating 50, fitted around the league-average anchor. The stat lines go
  through wOBA and the league's run values to WAA.
- **Calibrated on simulated seasons.** OOTP is a black box, so `calibrate.py` fits the lines to
  OOTP's own output: hundreds of seasons simmed on clones of a pristine league. It replaced a
  28-pivot Excel regression workbook and matched it on 100 of 110 constants; the other 10 were
  stale caches inside Excel.
- **Two-segment lines vs S-curves, per block.** The four pitching rate blocks (strikeouts from
  STU, unintentional walks from CON, home runs from HRR, BABIP from PBABIP) can also use a fitted
  logistic S-curve. For BLM the choice is per block and per role: the S-curve wins only when it is
  monotone and beats the two-segment line's error on the real season by more than 5%. TGS uses an
  all-or-nothing rule. Right now TGS runs S-curves on all four blocks; BLM runs them on starters'
  strikeouts and home runs and on relievers' walks, home runs and BABIP.
- **Level matching.** Both curve types are shifted so the projected league rate over the live
  player population equals the league's actual rate for the season.
- **Role stuff shift.** The old sheet moved every pitcher's stuff a flat 5 points between starter
  and reliever roles. The archive says OOTP does not: of 2,211 TGS role switches, 51% kept the
  same stuff and 49% gained 5. The engine now uses each pitcher's own expected gain, from his
  arsenal and stuff level, measured on the league's own switches. A pitcher whose switch is on
  record gets what OOTP actually did.
- **Other measured layers.** Monotone fielding curves, refits of the hitter tails, and a fitted
  run-value exchange rate between hitters and pitchers.
- **Park layer.** Two bases: Neutral (all parks equal) and My Park (50% your home park and 50% the
  average of the other MLB parks, per outcome and per batter hand). Factors come from the league's
  StatsPlus park export. Your home park follows the "my team" setting.

### Measured, not assumed

Wherever a constant could be measured from the game instead of guessed, it was.

- OOTP's published potential has no platoon split. Measured over fully developed players, it sits
  on the platoon blend (about 72/28 vs right/vs left, in 5-point steps). Both engines build each
  player's peak lines from his own current lean.
- Development is measured per year of age, not per pull, on the DEV league's true ratings
  (831,608 players).
- The My Park basis reproduces the workbook's own park cells to 1e-12.
- TGS and BLM are calibrated and measured separately. Nothing is pooled between them. The DEV
  league is the one shared source: it supplies the age curve and the ML training data.

---

## How it fits together

```
 OOTP league (online)                 OOTP client (local clones, DEV league)
        |                                       |
        | ratings + API (token)                 | ootp/winsim.py: screen automation,
        v                                       | clone, auto-play, bank the dumps
 StatsPlus --> tgs-viz/ingest/refresh.py        v
                        |              tgs-viz/engine/calibrate.py and the fits:
                        |              rate lines, S-curves, fielding curves,
                        |              run values, role stuff (per league)
                        v                       |
              tgs-viz/engine/  <----------------+
              hitters.py / pitchers.py: ratings -> stat lines -> WAA,
              park layer, split-aware potentials
                        |
                        v
              tgs-viz/backtest/: ratings archive, dev signals, ML scores
                        |
                        v
              tgs-viz/public/data/<LEAGUE>/*.json  -->  React app (Vite)
                                                          |
              tgs-viz/tools/run_task.py  <--  Control page (Vite plugin)
```

- **Ingestion** (`tgs-viz/ingest/`) pulls ratings, contracts, injuries, service time and draft
  results from StatsPlus. The draft class comes from your OOTP draft-pool export (BLM falls back
  to StatsPlus's draft-eligible flag when there is none). It archives every pull and builds the
  draft, Rule 5 and international boards. Every step's exit code is tracked. The final data date
  report reads the files on disk, so it reports what the app actually serves.
- **Backtesting** (`tgs-viz/backtest/`) holds the SQLite ratings archive, the development curves
  (a league-wide re-scout between two pulls spoils only that pair), season snapshots, dev signals
  and the ML code.
- **Control** (`tgs-viz/tools/`, `tgs-viz/control/`) holds the task registry, the runner, the
  settings module, the New League backend, the setup check and the Vite plugin that serves the
  Control page's API. Design: `tgs-viz/control/DESIGN.md`.
- **App** (`tgs-viz/src/`): React 19, Vite 7, Tailwind 4, Recharts. Roster Optimizer,
  Organization Builder and Team Projections share one optimizer, so every screen agrees.

### Settings

- `tgs-viz/tools/settings.defaults.json` holds the committed defaults: Python and Node commands,
  OOTP folders, the token file name, the app port and each league.
- `settings.local.json` in the repo folder holds your changes. The Setup check form writes it. It
  overrides the defaults key by key and is never committed.
- **Reset local settings** renames a broken local file and goes back to the defaults. No league
  data is touched.
- From a terminal: `python tgs-viz/tools/settings.py validate` checks both files.

---

## Repository layout

```
perfektprojections/
|-- Launch TGS.bat                 start the app (http://localhost:3000)
|-- Check Setup.bat                the setup check, in a console
|-- Get StatsPlus Ratings.bat      the other root bats: thin wrappers around run_task.py
|   (and 12 more)                  (the Jobs table lists every one)
|-- old bats (backup)/             the bats as they were before the Control page
|-- requirements.txt               main Python packages
|-- requirements-ml.txt            ML Python packages
|-- WHICH BUTTON.docx              the operator's guide: what to run, when
|-- STATUS.md                      engineering log and handoff notes
|-- ootp/                          OOTP automation (winsim, clone cleanup) and the ootp bats
|-- tgs-viz/
|   |-- tools/                     task registry, runner, settings, New League, setup check
|   |-- control/                   Vite plugin for the Control page, and DESIGN.md
|   |-- engine/                    projection engine, calibration and fits
|   |   `-- calib/<LEAGUE>/        fitted constants and curves per league
|   |-- ingest/                    StatsPlus ingestion, boards, pull report
|   |-- backtest/                  ratings archive, vintages, dev signals, ML (ml/)
|   |-- src/                       React app
|   `-- public/data/<LEAGUE>/      the datasets the app reads
`-- The Sheets <LEAGUE>/           Excel workbooks the engine reads its constants from
                                   (the calibration writes them)
```

OOTP notes:

- TGS runs on OOTP 26. BLM, Regular Game and DEV run on OOTP 27. The saved_games folders are
  settings, so another layout needs only a Setup check change.
- The sim tool never sims a real league or a pristine master. It only sims clones and the DEV
  league.
- The screen automation matches button images in `ootp/buttons/` captured on the author's PC. On
  another screen you may need to capture them again; see `ootp/README.md`.

---

## Tests

Run these from the repo folder.

| Test | Command |
|---|---|
| Bat equivalence (18 bats, 742 scenarios) | `python tgs-viz\tools\tests\test_bat_equivalence.py` |
| Runner | `set TGS_SELFTEST=1` and a temporary `TGS_CONTROL_DIR`, then `python -m unittest discover -s tgs-viz\tools\tests -p "test_run_task.py"` |
| Task catalog | `python tgs-viz\tools\tests\test_catalog.py` |
| Settings, New League, setup check | `python tgs-viz\tools\tests\test_settings_defaults.py`, `test_new_league.py`, `test_doctor.py` |
| Plugin | `node tgs-viz\control\test\fileMap.test.mjs`, `guards.test.mjs`, `pythonMain.test.mjs` |
| Plugin against a test server | `api.smoke.mjs`, `restart.smoke.mjs`, `failsafe.smoke.mjs` in `tgs-viz\control\test` (ports and variables in DESIGN.md, section 15) |
| App logic | `node tgs-viz\tests\client\softMerge.test.mjs`, `inputConditions.test.mjs` |

Test servers never use port 3000. With `TGS_SELFTEST=1`, the Control page also shows harmless self
test tasks.

---

## Credit

Built on the rating systems of OOTP 26 and 27 and on the original Excel regression work of
YourKidnies.
