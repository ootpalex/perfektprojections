"""Task registry for the Control panel and the bat wrappers (DESIGN.md 3.3, 4).

build_registry(settings_module, state) returns the task list as plain,
JSON-ready dicts. run_task.py runs them; the catalog (run_task.py --list-json)
shows them on the Control page.

The banner and echo text of the 18 old bats lives in T below, stored as cmd
prints it (carets removed). The copies under tests/legacy_bats are test
fixtures only and are never read here.

Stdlib only. Must import fast: no winsim, numpy, openpyxl or statsplus.
"""
import copy
import json
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELFTEST_SCRIPT = r"tgs-viz\tools\selftest_steps.py"
NEW_LEAGUE = r"tgs-viz\tools\new_league.py"

GROUPS = [
    {"id": "everyday", "title": "Everyday"},
    {"id": "leagues", "title": "Your leagues"},
    {"id": "season", "title": "Season end"},
    {"id": "calibration", "title": "Calibration and clone sims"},
    {"id": "dev", "title": "DEV research league and ML"},
    {"id": "ootp", "title": "OOTP tools"},
    {"id": "setup", "title": "Setup and checks"},
    {"id": "selftest", "title": "Self tests"},
]

JOB_ID_PATTERN = r"^\d{8}-\d{6}-[A-Za-z0-9_.-]+-[0-9a-f]{4}$"
SYNC_COUNT = r"^\s+(\d+) cell\(s\) will change"
CLEANUP_COUNT = r"will DELETE (\d+) clone league"
NO_RELOAD = "The open app updates itself; no reload needed."

# Banner and echo text ported from the old bats, as cmd prints it. Keys are
# <task>.<part>; placeholders in {} are filled at run time.
T = {
    'ratings.banner': [
        '',
        ' ===============================================',
        '   Pull player ratings from StatsPlus  (TGS + BLM)',
        ' ===============================================',
        '',
        ' With a StatsPlus token saved for each league (StatsPlus Tokens.txt),',
        ' this updates TGS and BLM in one run and asks for nothing. A token lasts',
        ' 90 days. Then paste the new one into StatsPlus Tokens.txt.',
        '',
        ' A league with no saved token needs your browser login instead: two values',
        ' from your browser while logged in to statsplus.net:  sessionid  and  csrftoken',
        '   F12  ->  Application (or Storage)  ->  Cookies  ->  statsplus.net',
        ' (A browser login is per-league: it updates only the league your browser',
        '  is signed into right now. The other league keeps its last data.',
        '  The report at the end shows exactly what the app is serving.)',
        '',
    ],
    'ratings.none': [
        ' Tip: Paste a token for each league into StatsPlus Tokens.txt. After that,',
        ' this bat asks for no cookies and updates both leagues in one run.',
        '',
    ],
    'ratings.both': [
        ' StatsPlus tokens are saved for TGS and BLM: no browser cookies needed.',
    ],
    'ratings.one': [
        ' A StatsPlus token is saved for {have}, but not for {notok}.',
        ' Paste the {notok} token into StatsPlus Tokens.txt. Then this bat asks for nothing.',
        ' To update {notok} in this run anyway, open statsplus.net/{noslug} in your browser',
        ' (logged in) and paste its cookies below. Press Enter to skip {notok} this run.',
        '',
    ],
    'ratings.tgs_ratings': [
        '',
        ' Working... pulling TGS, then BLM. StatsPlus builds each export on its',
        ' end, so this can take a couple of minutes. Leave this window open.',
        '',
        ' --- TGS (OSA ratings) ---',
    ],
    'ratings.tgs_draft': [
        '',
        ' --- TGS draft board (from your OOTP draft-pool CSV + the pull) ---',
        " (Export the pool from OOTP's Amateur Draft screen to import_export first.",
        "  Skips automatically if the CSV isn't there.)",
    ],
    'ratings.tgs_r5': [
        '',
        ' --- TGS Rule 5 pool (from your OOTP R5 draft-pool export + the pull) ---',
        " (Skips automatically if the CSV isn't there.)",
    ],
    'ratings.blm_ratings': [
        '',
        ' --- BLM (scouted ratings) ---',
    ],
    'ratings.blm_draft': [
        '',
        ' --- BLM draft board (pool CSV if present, else the draft_eligible API; live picks applied) ---',
    ],
    'ratings.blm_r5': [
        '',
        ' --- BLM Rule 5 pool (from your OOTP R5 draft-pool export + the pull) ---',
        " (Skips automatically if the CSV isn't there.)",
    ],
    'ratings.agecurve': [
        '',
        ' --- Age curves (measured dev rates; auto-skips short/contaminated archives) ---',
    ],
    'ratings.trends': [
        '',
        ' --- Rating trends (app history panel) ---',
    ],
    'ratings.devsignals': [
        '',
        ' --- Dev signals (growth, gains and chances from the DEV grid, per 16-26 year old) ---',
    ],
    'ratings.ml': [
        '',
        ' --- ML dev scores (one model set per league, on the new pulls; no retraining) ---',
    ],
    'ratings.report': [
        '',
    ],
    'ratings.fails': [
        '  Steps that did not update:{fails}',
        '  (each one said why above - a league with no token and no login this run is normal)',
    ],
    'ratings.end': [
        '',
    ],
    'history.banner_a': [
        '',
        ' ===============================================',
        '   Pull PAST ratings from StatsPlus  (one league)',
        ' ===============================================',
        '',
        ' What this does: StatsPlus can now give the ratings as they were on a',
        ' past game date. This asks for one snapshot every 6 game months',
        " (Jan 1 and Jul 1 of each game year, back to where the league's history",
        ' starts) and stores each one in the ratings archive under its game date',
        " (the date inside the league, not today's real date). It never changes",
        " the app's current player values: those still come from your latest",
        ' normal pull. It adds history for the rating trends, the dev signals',
        ' and the ML dev scores.',
        '',
    ],
    'history.banner_b': [
        ' A second run asks StatsPlus for almost nothing: dates already stored,',
        ' and dates StatsPlus had no snapshot for last time, are skipped. It runs',
        ' one extra check job only when no token is saved for the league, or',
        ' when the league has played on since your last Get StatsPlus Ratings run.',
        " Each snapshot is checked before it is stored: if StatsPlus sends today's",
        ' ratings for a past date, or repeats a date, nothing from it is stored.',
        '',
        ' Login: the saved StatsPlus token of the league (StatsPlus Tokens.txt',
        ' saves one per league). With no saved token, this asks for your browser',
        ' cookies instead, and a browser login works for ONE league: the league',
        ' your browser is signed into right now.',
        '',
    ],
    'history.invalid': [
        ' Please type TGS or BLM.',
    ],
    'history.token': [
        '',
        ' Using your saved {league} StatsPlus token. No browser cookies needed.',
    ],
    'history.notoken': [
        '',
        ' No StatsPlus token is saved for {league}. A token in StatsPlus Tokens.txt',
        ' and removes this step. For now your browser login works: your browser',
        ' must be signed into {league} on statsplus.net.',
        ' You need two values from your browser while logged in to',
        ' statsplus.net:  sessionid  and  csrftoken',
        '   F12  ->  Application (or Storage)  ->  Cookies  ->  statsplus.net',
        '',
    ],
    'history.run': [
        '',
        ' --- {league}: past rating snapshots from StatsPlus ---',
    ],
    'history.agecurve': [
        '',
        ' --- {league} age curves (prices each new snapshot once, then reuses it) ---',
    ],
    'history.trends': [
        '',
        ' --- Rating trends (app history panel) ---',
    ],
    'history.devsignals': [
        '',
        ' --- {league} dev signals (growth, gains and chances from the DEV grid, per 16-26 year old) ---',
    ],
    'history.ml': [
        '',
        ' --- {league} ML dev scores (scoring rows, then the score; no retraining) ---',
    ],
    'history.fails': [
        '  Steps that did not finish:{fails}',
        '  (each one said why above)',
    ],
    'history.stop2': [
        '',
        '  STOPPED (code 2): no StatsPlus login. No token is saved for {league} and',
    ],
    'history.stop3': [
        '',
    ],
    'history.stop3_cookie': [
        '  STOPPED (code 3): your browser is not signed into {league} on StatsPlus',
        '  (a login only pulls the league it is signed into).',
        '  Open statsplus.net/{slug} in your browser, sign in, then run this again.',
        '  A token in StatsPlus Tokens.txt removes this step.',
    ],
    'history.stop3_token': [
        '  STOPPED (code 3): StatsPlus refused your saved {league} token. The message',
        '  above says why (expired, unknown, or a login is needed). Copy the',
    ],
    'history.stop6': [
        '',
        '  STOPPED (code 6): the ratings StatsPlus sent do not look like {league}',
        '  (the player IDs and names do not match your {league} pulls). Nothing from',
        '  that date was stored. Check that you typed the right league, then run again.',
    ],
    'history.stop7': [
        '',
        "  STOPPED (code 7): StatsPlus sent TODAY's ratings for 3 past game dates",
        '  in a row and no past date came back this run, so it ignores the date',
        '  right now. Nothing from those dates was stored. Do not run this again',
        '  until StatsPlus past snapshots work.',
    ],
    'history.stop8': [
        '',
        '  STOPPED (code 8): StatsPlus pointed the job at another web site. Your',
        '  login was NOT sent there and nothing from that job was stored. Do not',
        '  run this again until the cause is found.',
    ],
    'history.stop9': [
        '',
        '  STOPPED (code 9): StatsPlus says past date ratings are NOT ENABLED',
        "  for {league}. Your login worked. Nothing was stored. The league's StatsPlus",
        '  owner has to switch the feature on first; then run this again.',
    ],
    'history.stop10': [
        '',
        "  STOPPED (code 10): the check job for today's ratings failed, and not",
        '  because of the login. The message above says why (no ratings,',
        '  StatsPlus not reachable, or too slow). Nothing was stored. Run',
        '  Get StatsPlus Ratings.bat first, then run this again.',
    ],
    'history.skipped': [
        '  Dates stored before the stop, if any, passed every check and stay stored',
        '  (the report above lists them).',
        '  The archive steps (age curves, rating trends, dev signals, ML scores)',
        '  were skipped this time.',
    ],
    'bank_season.banner_a': [
        '============================================================',
        '  BANK SEASON  -  save actuals + freeze projections',
        '------------------------------------------------------------',
        '  THE ORDER MATTERS at a season end:',
        '   1. FIRST run "Get StatsPlus Ratings.bat"  (fresh ratings',
        '      pull - ratings are PERISHABLE; the stats can always be',
        '      re-fetched later, the ratings as-of-now cannot)',
        '   2. THEN run this.',
        '  It saves, for TGS then BLM:',
        "   - The season's ACTUAL batting/pitching/fielding stats",
        '     (backtest\\actuals\\LEAGUE\\year\\*.csv + meta.json marking',
        '     whether the season was complete)',
        '   - A dated snapshot of the CURRENT projections + ratings',
        '     cache (backtest\\snapshots\\LEAGUE\\in-game-date\\)',
        '  A loud warning appears if the ratings cache is stale.',
    ],
    'bank_season.banner_b': [
        '============================================================',
        '',
    ],
    'bank_season.tgs_actuals': [
        ' --- TGS: season actuals (MLB level) ---',
    ],
    'bank_season.tgs_snapshot': [
        '',
        ' --- TGS: projection snapshot ---',
    ],
    'bank_season.blm_actuals': [
        '',
        ' --- BLM: season actuals (MLB level) ---',
    ],
    'bank_season.blm_actuals_fail': [
        '  (warning: BLM actuals failed - its API may differ; continuing)',
    ],
    'bank_season.blm_snapshot': [
        '',
        ' --- BLM: projection snapshot ---',
    ],
    'bank_season.blm_snapshot_fail': [
        '  (warning: BLM snapshot failed - continuing)',
    ],
    'bank_season.ok': [
        '',
        '============================================================',
        '  Done. Actuals are in tgs-viz\\backtest\\actuals\\ and the',
        '  projection snapshots in tgs-viz\\backtest\\snapshots\\.',
        '  Old actuals get a timestamped .bak; snapshots never',
        '  overwrite (a -2 suffix is added instead).',
        '============================================================',
    ],
    'bank_season.fails': [
        '',
        '============================================================',
        '  NOT done:{fails}',
        '  Each one says why above. Fix that, then run this again.',
        '  (A league that is mid-season is skipped, not failed.)',
        '============================================================',
    ],
    'bank_dev.banner': [
        '============================================================',
        '  BANK DEV SEASONS  -  no simming',
        '------------------------------------------------------------',
        '  For when you sim DEV TESTS by hand inside OOTP. OOTP writes',
        '  the yearly CSV dump by itself at every new year. This bat',
        '  only picks up the dumps that are not banked yet, stores them',
        '  as ratings vintages, rebuilds the DEV trends file and makes',
        "  sure DEV is in the web app's league list. Then it retrains",
        '  the ML dev models on every banked season and rescores TGS',
        '  and BLM (step 4b is LONG: about an hour per 150 banked',
        '  seasons on this PC; let it finish).',
        '  Safe to run any time; already-banked years are skipped.',
        '============================================================',
        '',
    ],
    'bank_dev.dump': [
        ' --- 1. bank new yearly dumps ---',
    ],
    'bank_dev.trends': [
        '',
        ' --- 2. rebuild the DEV trends file ---',
    ],
    'bank_dev.value': [
        '',
        " --- 2b. value the new DEV seasons with each league's engine (only new seasons) and rebuild the DEV age curve ---",
    ],
    'bank_dev.odds': [
        '',
        ' --- 3. rebuild the DEV odds grid (regular odds by age, Pot and growth) ---',
    ],
    'bank_dev.rating_odds': [
        '',
        ' --- 3b. rebuild the Make-it odds tables (odds by age and one rating band) ---',
    ],
    'bank_dev.devsignals': [
        '',
        ' --- 4. dev signals for TGS and BLM (growth, gains and chances from the DEV grid, per 16-26 year old) ---',
    ],
    'bank_dev.ml': [
        '',
        ' --- 4b. retrain the ML dev models, one set per league (LONG, let it finish) ---',
    ],
    'bank_dev.manifest': [
        '',
        " --- 5. register DEV in the web app's league list ---",
    ],
    'bank_dev.ok': [
        '',
        '============================================================',
        '============================================================',
    ],
    'bank_dev.fail': [
        '',
        '============================================================',
        '  Something failed above. Nothing is lost: the dumps stay in',
        "  the league's dump folder. Fix the message and rerun.",
        '============================================================',
    ],
    'grind_tgs.banner': [
        '============================================================',
        '  TGS GRIND  -  fully automatic, runs until YOU stop it',
        '------------------------------------------------------------',
        '  Each cycle: 10 clones x 10 seasons (~100 seasons), then it',
        '  AUTOMATICALLY recalibrates (constants -> sheets -> webapp),',
        '  refreshes every fitted layer, archives the season data and',
        '  deletes the spent clone saves. Then it starts the next',
        '  cycle. No prompts, no manual steps, no leftovers.',
        '',
        '  START STATE: OOTP 26 open INSIDE any league EXCEPT the',
        '  Baseline master. Then hands off the mouse/keyboard.',
        '',
        {"console": '  STOP: close this window (or Ctrl+C). Every finished cycle',
         "job": '  STOP: press Stop after this cycle on the page. Every finished cycle'},
        '  is already banked, so stopping never loses banked seasons',
        '  (at worst the current in-progress clone is discarded).',
        '============================================================',
        '',
    ],
    'grind_tgs.cycle': [
        '',
        '################  CYCLE {cycle}  -  simming 10 clones (~100 seasons)  ################',
    ],
    'grind.winsim_fail': [
        '  winsim reported a problem - recalibrating what finished, then stopping.',
    ],
    'grind_tgs.recal': [
        '',
        '################  CYCLE {cycle}  -  recalibrating  ################',
    ],
    'grind.stopped': [
        '',
        '============================================================',
        '  Stopped after a sim problem - everything that finished IS',
        '  banked. Check the messages above, fix, and rerun.',
        '============================================================',
    ],
    'grind.fail': [
        '',
        '============================================================',
        '  A recalibrate step failed - sim data is still on disk and',
        '  in the archive; nothing further was changed. See above.',
        '============================================================',
    ],
    'grind_blm.banner': [
        '============================================================',
        '  BLM GRIND  -  fully automatic, runs until YOU stop it',
        '------------------------------------------------------------',
        '  Each cycle: 10 clones of master "6" x 10 seasons, then it',
        '  AUTOMATICALLY recalibrates BLM (constants -> sheets ->',
        '  webapp), refreshes the fitted layers, archives the season',
        '  data and deletes the spent clone saves. Then repeats.',
        '',
        '  START STATE: OOTP 27 open INSIDE any league EXCEPT the',
        '  master "6". Then hands off the mouse/keyboard.',
        '  (Grind TGS and Grind BLM cannot run at the same time -',
        '   they share your mouse.)',
        '',
        {"console": '  STOP: close this window (or Ctrl+C). Every finished cycle',
         "job": '  STOP: press Stop after this cycle on the page. Every finished cycle'},
        '  is already banked.',
        '============================================================',
        '',
    ],
    'grind_blm.cycle': [
        '',
        '################  BLM CYCLE {cycle}  -  simming 10 clones (~100 seasons)  ################',
    ],
    'grind_blm.recal': [
        '',
        '################  BLM CYCLE {cycle}  -  recalibrating  ################',
    ],
    'grind_blm.stopped': [
        '',
        '============================================================',
        '  Stopped after a sim problem - everything that finished IS',
        '  banked. Check the messages above, fix, and rerun.',
        '============================================================',
    ],
    'grind_blm.fail': [
        '',
        '============================================================',
        '  A recalibrate step failed - sim data is still on disk and',
        '  in the archive; nothing further was changed. See above.',
        '============================================================',
    ],
    'recal_tgs.banner': [
        '============================================================',
        '  RECALIBRATE TGS  -  clone sims  ->  regression constants',
        '                     ->  projection sheets  ->  webapp data',
        '------------------------------------------------------------',
        '  1. Computes every regression constant from the clone dumps',
        '     on disk (C:\\OOTP 26\\data\\saved_games\\*tgs*.lg).',
        '     Incomplete clones are skipped automatically.',
        '  2. Shows you exactly what would change in the sheets and',
        '     asks before writing (timestamped .bak made first).',
        '  3. Refits the fitted layers and promotes the S-curves if',
        '     they pass their gates.',
        '  4. Rebuilds the Calibration page data and the webapp data',
        '     from the cached StatsPlus pull.',
        '  5. Offers to delete the clone saves (their data is archived).',
        '  No Excel needed. Takes 1 to 3 minutes plus your answers.',
        '  (Sim more clones first with "4 - Sim TGS.bat" if you want',
        '   a bigger sample.)',
        '============================================================',
        '',
    ],
    'recal_tgs.cleanup': [
        '',
        '  Clone data is archived - the clone leagues can be deleted now',
        {"console": '  (your real leagues are never touched; answer N to keep them).',
         "job": '  (your real leagues are never touched; press Keep to keep them).'},
    ],
    'recal_tgs.ok': [
        '',
        '============================================================',
        '  new constants next time you open them (no Refresh All).',
        '============================================================',
    ],
    'recal.fail': [
        '',
        '  Something failed above - nothing further was changed.',
    ],
    'recal_blm.banner': [
        '============================================================',
        '  RECALIBRATE BLM  -  metadata + regressions  ->  sheets  ->  webapp',
        '------------------------------------------------------------',
        '  Two layers, one run:',
        '  A. METADATA = the real BLM season. StatsPlus stats API + your',
        '     season-end ratings pull build 7 of the 9 input tabs. Run',
        '     "Get StatsPlus Ratings" first so the pull is the season-end one.',
        "     YOU paste the pitchers' AS-STARTER stats into 'SP Data' and",
        "     AS-RELIEVER stats into 'RP Data' in The Sheets BLM\\25 Metadata",
        '     .xlsx (StatsPlus has no stats split by role). Your paste is',
        '     used as it is.',
        "  B. REGRESSIONS = clone sims run with BLM's league settings. Pools",
        '     the archived sample (tgs-viz\\engine\\calib\\BLM) with any NEW',
        "     complete clone sims in OOTP 27's saved_games (0blm*.lg). It",
        '     runs AFTER the metadata because the pitching intercepts are',
        '     stated at the league-average ratings the metadata just moved.',
        '     This step never sims anything itself.',
        '  Then: moves both into The Sheet Hitters / Pitchers (backups made,',
        '  every change listed), refits the fitted layers, promotes the',
        '  S-curves if they pass their gates, rebuilds the webapp data.',
        '  It does not stop to ask. Running it means update everything.',
        '============================================================',
        '',
    ],
    'recal_blm.a1': [
        '',
        ' --- A1. metadata inputs from StatsPlus ---',
    ],
    'recal_blm.reminder': [
        '',
        ' ============================================================',
        "  REMINDER: paste 'SP Data' (as starter) and 'RP Data' (as",
        '  reliever) into  The Sheets BLM\\25 Metadata.xlsx,  save, and',
        {"console": '  CLOSE Excel. Already done? Just press a key.',
         "job": '  CLOSE Excel. Already done? Press Continue on the page.'},
        ' ============================================================',
    ],
    'recal_blm.a2': [
        '',
        ' --- A2. your SP/RP paste ---',
    ],
    'recal_blm.a3': [
        '',
        ' --- A3. metadata Data Points (Python port of 25 Metadata) ---',
    ],
    'recal_blm.b': [
        '',
        ' --- B. regressions from the BLM clone archive, centred on the NEW anchors ---',
    ],
    'recal_blm.sync': [
        '',
        ' --- move the metadata + regressions into The Sheet Hitters / Pitchers (backups made) ---',
    ],
    'recal_blm.refresh': [
        '',
        ' --- webapp data from the cached pull with the new constants ---',
    ],
    'recal_blm.cleanup': [
        '',
        '  Clone data is archived - the clone leagues can be deleted now',
        {"console": '  (your real leagues are never touched; answer N to keep them).',
         "job": '  (your real leagues are never touched; press Keep to keep them).'},
    ],
    'recal_blm.ok': [
        '',
        '============================================================',
        '============================================================',
    ],
    'recal_blm.fail': [
        '',
        '  Something failed above - nothing further was changed.',
    ],
    'sim_dev.banner': [
        '============================================================',
        '  SIM DEV LEAGUE  -  {years} seasons of "DEV TESTS"  ->  ratings archive',
        '------------------------------------------------------------',
        '  DEV TESTS is a plain OOTP 27 league, every team AI-controlled,',
        '  simmed in place year after year. Its yearly CSV dump gives',
        '  true ratings and personalities: no scouting, no StatsPlus.',
        '  Each run: load DEV TESTS, auto-play {years} seasons, wait for the',
        '  last dump, bank the dumps as ratings vintages, rebuild the DEV',
        '  trends file for the web app. Run it again any time: it starts',
        '  from the last dump on disk. Dumps are never deleted or moved.',
        '',
        '  START STATE: OOTP 27 open and INSIDE a league. Any league is',
        '  fine, DEV TESTS itself too (save it first: the tool reloads',
        '  it from disk). The main menu alone is NOT enough: the tool',
        '  drives FILE -> Load Game. Not running as administrator.',
        '  In DEV TESTS, "Export CSV files after each simulated season"',
        '  must be ON in the game settings, or nothing gets banked.',
        '',
        '  FIRST TIME ONLY, before this bat, check the Load Game row and',
        '  the date picker on the real league (neither one sims):',
        '    python ootp\\winsim.py --league DEV --test-load "DEV TESTS"',
        '    python ootp\\winsim.py --league DEV --test-year',
        '  then look at ootp\\_diag_loaded.png and _diag_after_setyear.png.',
        '',
        '  Hands off the mouse and keyboard once it starts.',
        {"console": '  ABORT: slam the mouse into a screen corner, or Ctrl+C.',
         "job": '  ABORT: slam the mouse into a screen corner, or press Kill now on the page.'},
        {"console": '  Ctrl+C stops this window, not the sim already running in OOTP.',
         "job": '  Kill now stops the task, not the sim already running in OOTP.'},
        '  Another count: "Sim Dev League.bat 3" sims 3 seasons.',
        '============================================================',
        '',
    ],
    'sim_dev.sim': [
        '',
        ' --- 1. sim {years} season(s) ---',
    ],
    'sim_dev.bank': [
        '',
        ' --- 2. bank the yearly dumps as ratings vintages ---',
    ],
    'sim_dev.missing': [
        '  tgs-viz\\backtest\\dump_vintages.py is missing. The seasons are simmed and on disk; nothing was banked.',
    ],
    'sim_dev.trends': [
        '',
        ' --- 3. rebuild the DEV trends file for the web app ---',
    ],
    'sim_dev.manifest': [
        '',
        " --- 4. register DEV in the web app's league list ---",
    ],
    'sim_dev.ok': [
        '',
        '============================================================',
        '============================================================',
    ],
    'sim_dev.fail': [
        '',
        '============================================================',
        '  Something failed above. Seasons already simmed stay on disk',
        "  in the league's dump folder; the next run starts from the",
        '  last dump. Fix the message above and rerun.',
        '============================================================',
    ],
    'sync.banner': [
        '============================================================',
        '  Sync Data Points  -  Metadata  ->  Sheets',
        '============================================================',
        '',
        '  TGS: use this after you refresh 25 Metadata.xlsx with new',
        '  league exports: open it in Excel, recalculate, and SAVE.',
        '  BLM: Recalibrate BLM builds its metadata from StatsPlus',
        '  (metadata-latest.json); this just re-pushes that JSON.',
        '',
        '  This copies the metadata constants (anchors, league rates,',
        '  fielding ratings, positional adjustments) into The Sheet',
        '  Hitters/Pitchers "Data Points" tabs. The REGRESSION half',
        '  always comes from the Python calibration (constants-latest',
        '  .json), NOT from 25 Regressions.xlsx - so this can never',
        '  overwrite a calibration. It shows every change and asks',
        '  before writing. Your next "Get StatsPlus Ratings" pull',
        '  then updates the web app.',
        '',
        '============================================================',
        '',
    ],
    'sync.ok': [
        '',
        '============================================================',
        '  Done. Run "Get StatsPlus Ratings.bat" to rebuild the app',
        '============================================================',
    ],
    'sync.fail': [
        '',
        '  Something failed above - nothing further was changed.',
    ],
    'dispersal.banner': [
        '============================================================',
        '  TGS DISPERSAL DRAFT BOARD',
        '------------------------------------------------------------',
        '  Pool = every player in the four folding orgs:',
        '    Atlanta Hammers / Detroit Tigers /',
        '    San Francisco Giants / Seattle Mariners',
        '  Ratings come from the cached StatsPlus pull (run',
        '  "Get StatsPlus Ratings.bat" first if it\'s stale).',
        "  As picks happen, add each drafted player's name to",
        '  dispersal_drafted.txt (one per line) and re-run this.',
        '  No Excel, no OOTP export needed.',
        '============================================================',
        '',
    ],
    'dispersal.ok': [
        '',
    ],
    'dispersal.fail': [
        '',
        '  NOT updated. The reason is above. Fix that, then run this again.',
    ],
    'draft.banner': [
        '============================================================',
        '  DRAFT BOARDS  -  OOTP pool export + StatsPlus ratings',
        '------------------------------------------------------------',
        '  Before running, for the league that is drafting:',
        '   1. In OOTP: Amateur Draft screen -> export the DRAFT POOL',
        '      report to CSV. (BLM exports hitters and pitchers as two',
        '      separate files - both are picked up automatically.)',
        '   2. Make sure your ratings pull is recent',
        '      ("Get StatsPlus Ratings.bat").',
        '  Drafted players drop off automatically from the live',
        '  StatsPlus pick list - just re-run this as picks come in.',
        '  A league with no pool export is skipped harmlessly.',
        '  No Excel needed.',
        '============================================================',
        '',
    ],
    'draft.tgs': [
        ' --- TGS ---',
    ],
    'draft.blm': [
        '',
        ' --- BLM ---',
    ],
    'draft.ok': [
        '',
        '============================================================',
        '============================================================',
    ],
    'draft.fails': [
        '',
        '============================================================',
        '  NOT updated:{fails}',
        '  Each one says why above. Fix that, then run this again.',
        '============================================================',
    ],
    'rg.banner': [
        '',
        ' ===============================================',
        '   Update Regular Game  (OOTP 27 save, BLM settings)',
        ' ===============================================',
        '',
        ' BEFORE running this: open Regular Game in OOTP and export the database',
        ' to CSV again (the same export as the first time). It goes to',
        '   saved_games\\Regular Game.lg\\import_export\\csv',
        ' Optional: for signing demands on the international board, also export',
        " OOTP's International Amateur Free Agents screen to its import_export folder.",
        '',
        " What this does: prices every player with BLM's engine settings, builds",
        " the draft board (this year's draft class) and the international list,",
        ' saves this export as a snapshot (so growth and rating trends build up as',
        ' you sim), then the dev signals and the ML dev chances (the BLM-trained',
        ' model). Running it again on the same export replaces that snapshot.',
        '',
    ],
    'rg.players': [
        ' --- Players, draft board, internationals, snapshot, rating trends ---',
    ],
    'rg.devsignals': [
        '',
        ' --- Dev signals ---',
    ],
    'rg.ml': [
        '',
        ' --- ML dev chances (MLB / Starter / Star %) ---',
    ],
    'rg.fails': [
        '',
        '  Steps that did not finish:{fails}',
        '  (each one said why above)',
        '',
    ],
    'o1.banner': [
        '============================================================',
        '  STEP 1  -  can the tool see your OOTP window?',
        '------------------------------------------------------------',
        '  Before you run this:',
        '    - open OOTP 26',
        '    - leave it on the MAIN MENU (or in a loaded league)',
        '============================================================',
        '',
    ],
    'o1.list': [
        '--- windows the tool can see (look for "Out of the Park Baseball 26") ---',
    ],
    'o1.grab': [
        '',
        '--- taking a screenshot of the OOTP window ---',
    ],
    'o1.ok': [
        '',
        '============================================================',
        '  If you saw the OOTP 26 window listed above and it said',
        '  "saved ...winsim_grab.png", you\'re good. Send that result',
        '  (and the ootp\\winsim_grab.png file) back to Claude.',
        '============================================================',
    ],
    'o2.banner': [
        '============================================================',
        '  GRAB A MENU  (OOTP 26)',
        '------------------------------------------------------------',
        '  This brings OOTP to the front, then counts down 6 seconds.',
        '  DURING the countdown, open the menu Claude asked for',
        '  (e.g. click FILE, or click PLAY) and LEAVE it open.',
        '  It screenshots while the menu is still showing.',
        '============================================================',
        '',
    ],
    'o2.ok': [
        '',
        '============================================================',
        '  Saved to ootp\\winsim_grab.png  -  send it to Claude.',
        '============================================================',
    ],
    'o3.banner': [
        '============================================================',
        '  PREVIEW  -  shows the plan, clones nothing, clicks nothing',
        '============================================================',
        '',
    ],
    'o3.ok': [
        '',
        '============================================================',
        '  If that looks right, run "4 - Sim TGS.bat" to do it for real.',
        '============================================================',
    ],
    'o4.banner': [
        '============================================================',
        '  SIM TGS  -  clones your Baseline league and auto-plays it',
        '------------------------------------------------------------',
        '  * Have OOTP 26 open INSIDE a league (any league EXCEPT the',
        '    Baseline master - the tool needs FILE->Load Game, and the',
        '    master must be closed so its files can be copied),',
        '    and NOT running as administrator',
        "    (if it is, the tool can't click it - see Claude's note).",
        '  * Runs 10 clones back-to-back (~10 seasons each, ~7-8 min',
        '    per clone with the new Baseline). Edit --runs to change.',
        '  * ABORT any time: slam the mouse into a screen corner.',
        '  * Do not touch the mouse/keyboard once it starts clicking.',
        '============================================================',
        '',
    ],
    'o4.ok': [
        '',
        '============================================================',
        '  Done. Next: "Recalibrate TGS.bat" (repo root) pools the new',
        '  clones into the constants and rebuilds the app data.',
        '============================================================',
    ],
    'ot.banner': [
        '============================================================',
        '  TEST YEAR PICKER  (diagnostic - safe)',
        '------------------------------------------------------------',
        '  Have OOTP 26 open with ANY league loaded (Baseline is fine',
        '  to just LOOK at - this never sims or clicks AUTO-PLAY).',
        '  It opens Play -> Specified Date and tries to set the year,',
        '  then STOPS and saves screenshots for Claude.',
        '  Keep hands off once it starts. Corner-slam to abort.',
        '============================================================',
        '',
    ],
    'ot.ok': [
        '',
        '============================================================',
        '  Done. Send Claude the text above, or just say "done" and',
        '  Claude will read the ootp\\_diag_*.png snapshots.',
        '============================================================',
    ],
}


# ---------------------------------------------------------------- builders

FLAG_NAMES = ("writes_app_data", "heavy", "long", "endless", "drives_ootp", "needs_ootp_closed",
              "needs_excel_closed", "network", "secret_inputs", "hidden", "read_only", "needs_archive")


def flags(**kw):
    out = {k: False for k in FLAG_NAMES}
    for k, v in kw.items():
        if k not in out:
            raise KeyError(k)
        out[k] = bool(v)
    return out


def py(*args):
    return ["@py"] + list(args)


def ml(*args):
    return ["@ml"] + list(args)


def node(*args):
    return ["@node"] + list(args)


def inp(name, type, label, help="", required=False, default=None, choices=None, fmt=None,
        min=None, max=None, ask_when=None, console=None, equals=None, from_argv=None,
        modes=("console", "job"), pattern=None):
    d = {"name": name, "type": type, "label": label, "help": help, "required": required,
         "default": default, "ask_when": ask_when, "console": console, "modes": list(modes)}
    if type == "choice":
        d["choices"] = choices or []
    if type == "secret" and fmt:
        d["format"] = fmt                       # "statsplus_token": the browser checks the token shape (10.4)
    if type == "text":
        d["format"] = fmt
        if min is not None:
            d["min"] = min
        if max is not None:
            d["max"] = max
        d["equals"] = equals
        if pattern:
            d["pattern"] = pattern
    d["from_argv"] = from_argv
    return d


def step(id, title, run=None, on_error="fail", tag=None, echo=None, app=False, kind="run", **kw):
    st = {"id": id, "title": title, "kind": kind, "echo": list(echo or []), "run": run,
          "when": None, "on_error": on_error, "tag": tag, "fail_echo": [],
          "writes_app_data": bool(app), "env": None, "set_flag": None, "job": None, "excel": None}
    st.update(kw)
    return st


def gate(id="start", text=None, input=None, echo=None, job_message=None):
    """A pause. start=True: the bat's pause before anything runs (console only;
    job mode uses the Start click, or the required confirm input named here)."""
    st = step(id, "Ready check" if id == "start" else "Your turn", kind="gate", echo=echo, on_error="fail")
    st["start"] = id == "start"
    st["input"] = input
    st["data"] = False if id == "start" else None
    if text:
        st["prompt"] = {"text": text, "choices": [{"id": "continue", "label": "Continue"},
                                                  {"id": "stop", "label": "Stop"}]}
    if job_message:
        st["job_message"] = job_message
    return st


def excel_check(id, folder, files=("The Sheet Hitters.xlsx", "The Sheet Pitchers.xlsx")):
    return step(id, "Check that Excel is closed", kind="excel_check",
                excel={"folder": folder, "files": list(files)})


def preview_confirm(preview, apply, regex, question, yes="Apply", no="Skip"):
    return {"kind": "preview_confirm", "preview": preview, "apply": apply, "count_regex": regex,
            "question": question, "yes_label": yes, "no_label": no}


def sync_job(argv, sheet):
    """Job-mode substitute for a sync_datapoints step that would ask y/N."""
    pre = [a for a in argv if a != "--write"]
    return preview_confirm(pre, pre + ["--write", "--yes"], SYNC_COUNT,
                           f"Apply these changes to {sheet}?")


def cleanup_job(argv):
    return preview_confirm(argv + ["--dry-run"], argv + ["--yes"], CLEANUP_COUNT,
                           "Delete these clone saves? Check the folder names above first.",
                           yes="Delete", no="Keep")


def task(id, title, description, group, steps, *, leagues=(), bat=None, requires=(), fl=None,
         locks=(), time="", inputs=(), banner=None, loop=None, finish=None, stop_modes=None,
         rollback=None, expand=None):
    fl = fl or flags()
    if stop_modes is None:
        stop_modes = ["after_cycle", "after_step", "kill"] if fl["endless"] else ["after_step", "kill"]
    t = {"id": id, "title": title, "description": description, "group": group,
         "leagues": list(leagues), "bat": bat, "requires_leagues": list(requires), "flags": fl,
         "locks": list(locks), "time": time, "inputs": list(inputs),
         "banner": list(banner if banner is not None else ["", " " + title, ""]),
         "steps": list(steps), "loop": loop, "finish": finish or fin(), "stop_modes": stop_modes,
         "rollback": rollback}
    if expand:
        t["expand"] = expand
    return t


def fin(style="fails", ok=None, fails=None, fail=None, stopped=None, exit_ok=None, exit_fail=1,
        exit_stopped=1, report_step=None, report_verdict="strict"):
    """Finish block. exit_ok/exit_fail None = the exit code of the last command
    the bat ran (cmd semantics, 6.4)."""
    return {"style": style,
            "ok_echo": list(ok if ok is not None else ["", "  Done."]),
            "fails_echo": list(fails if fails is not None else
                               ["", "  Steps that did not finish:{fails}", "  (each one said why above)"]),
            "fail_echo": list(fail if fail is not None else
                              ["", "  Something failed above. The steps after it did not run."]),
            "stopped_echo": list(stopped or []),
            "report_step": report_step, "report_verdict": report_verdict,
            "exit": "bat", "exit_ok": exit_ok, "exit_fail": exit_fail, "exit_stopped": exit_stopped}


def headers(steps):
    """Give each step of a new (non-bat) task a ' --- title ---' header."""
    for s in steps:
        if s["kind"] in ("run", "probe") and not s["echo"]:
            s["echo"] = ["", f" --- {s['title']} ---"]
    return steps


def replace_line(lines, old, new):
    out = list(lines)
    i = out.index(old)
    out[i:i + 1] = new if isinstance(new, list) else [new]
    return out


# ---------------------------------------------------------------- computed defaults

WINSIM = r"ootp\winsim.py"
CLEANUP = r"ootp\cleanup_clones.py"


def script_of(argv):
    """The script path in an argv with a marker (@py x.py ...), or ''."""
    if not argv:
        return ""
    return str(argv[1]) if len(argv) > 1 else ""


def _arg(argv, flag):
    try:
        return argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def default_drives_ootp(argv):
    if script_of(argv) != WINSIM:
        return False
    a = set(argv)
    if "--runs" in a and "--dry-run" not in a:
        return True
    return bool(a & {"--sim", "--test-year", "--test-load", "--peek-load"})


def default_data(t, s):
    if t["flags"]["read_only"]:
        return False
    if s.get("data") is not None:
        return bool(s["data"])
    if s["kind"] == "gate" and s.get("start"):
        return False
    sc = script_of(s.get("run"))
    if sc in (WINSIM, CLEANUP):
        return False
    if sc == NEW_LEAGUE and len(s["run"]) > 2 and s["run"][2] == "token":
        return False
    return True


def league_of_data_file(rel):
    """The fileMap league (9.2) of a path under public/data: an id, '*' or None (ignored)."""
    rel = rel.replace("\\", "/").lstrip("/")
    if rel in ("leagues.json", "dev_rating_odds.json"):
        return "*"
    m = re.match(r"^([A-Za-z0-9_-]{1,16})/([^/]+)\.json$", rel)
    if not m:
        return None
    lg, name = m.group(1), m.group(2)
    if name == "age_curve":
        return "*" if lg == "DEV" else lg
    if name in ("rating_trends", "calibration", "park_lineup_values") or name in PLAYER_FILES:
        return lg
    return None


PLAYER_FILES = {"hitters", "pitchers", "hitters_park", "pitchers_park", "hitters_draft", "pitchers_draft",
                "hitters_draft_park", "pitchers_draft_park", "hitters_draft_all", "pitchers_draft_all",
                "hitters_draft_all_park", "pitchers_draft_all_park", "draft_picks", "iafa", "r5", "parks",
                "park_list", "metadata", "market_fit", "dev_signals", "dev_ml"}


def default_app_leagues(argv, trends_leagues):
    """app_leagues of a writer step (table in 9.3)."""
    sc = script_of(argv).replace("/", "\\")
    base = sc.rsplit("\\", 1)[-1]
    lg = _arg(argv, "--league")
    if base in ("refresh.py", "draft.py", "r5.py", "iafa.py", "export_calibration.py",
                "dev_signals.py", "score.py"):
        return [lg] if lg else []
    if base == "agecurve_fit.py":
        return ["*"] if lg == "DEV" else ([lg] if lg else [])
    if base == "bank_market_fit.mjs":
        return [argv[2]] if len(argv) > 2 else []
    if base == "ratings_db.py" and "--export" in argv:
        return [lg] if lg else list(trends_leagues)
    if base == "dev_rating_odds.py":
        return ["*"]
    if base == "dev_odds.py":
        return []
    if base == "parks.py":
        return ["TGS", "BLM"]
    if base == "extract_data.py":
        return ["*"]
    if base == "export_league.py":
        return [lg, "*"] if lg else ["*"]
    if base == "new_league.py" and len(argv) > 2 and argv[2] in ("register", "register-manifest", "refresh-manifest",
                                                                 "remove", "rollback"):
        return [lg or "{id}", "*"]
    if base == "selftest_steps.py" and len(argv) > 3 and argv[2] in ("touch", "corrupt"):
        f = argv[3]
        l2 = league_of_data_file(f)
        return [l2] if l2 else []
    return []


def finalize(t, trends_leagues):
    """Fill the defaults: the task.<id> lock, and per step data, drives_ootp, app_leagues."""
    if t["flags"]["read_only"]:
        t["locks"] = []
    else:
        own = "task." + t["id"]
        t["locks"] = [own] + sorted(n for n in set(t["locks"]) if n != own)
    for s in t["steps"]:
        s["data"] = default_data(t, s)
        if s.get("drives_ootp") is None:
            s["drives_ootp"] = default_drives_ootp(s.get("run"))
        if s.get("app_leagues") is None:
            s["app_leagues"] = default_app_leagues(s.get("run") or [], trends_leagues) if s["writes_app_data"] else []
        if s.get("job"):
            s["job"].setdefault("drives_ootp", False)
    return t


# ---------------------------------------------------------------- inputs used by several tasks

def cookie_inputs(ask_sid, ask_csrf=None):
    help_text = ("Only needed when no StatsPlus token is saved for the league. From your browser "
                 "while logged in to statsplus.net: F12, Application (or Storage), Cookies, statsplus.net. "
                 "Leave blank to skip.")
    return [
        inp("sessionid", "secret", "Browser cookie: sessionid", help_text, ask_when=ask_sid),
        inp("csrftoken", "secret", "Browser cookie: csrftoken", help_text,
            ask_when=ask_csrf if ask_csrf is not None else ask_sid),
    ]


def ootp_ready(text):
    return inp("ootp_ready", "confirm", text, "Check this before you press Start.", required=True,
               default=False, modes=("job",))


def runs_input(default=10):
    return inp("runs", "text", "Clones per cycle", "How many clone leagues to sim (1 to 50).",
               default=str(default), fmt="int", min=1, max=50)


def say_choices(ids):
    ids = list(ids)
    if len(ids) <= 1:
        return "".join(ids)
    return ", ".join(ids[:-1]) + " or " + ids[-1]


def env_cookie():
    return {"STATSPLUS_COOKIE": "@cookie"}


# ---------------------------------------------------------------- the 18 bat tasks

REFRESH, DRAFT, R5 = r"tgs-viz\ingest\refresh.py", r"tgs-viz\ingest\draft.py", r"tgs-viz\ingest\r5.py"
AGECURVE = r"tgs-viz\engine\agecurve_fit.py"
RATINGS_DB = r"tgs-viz\backtest\ratings_db.py"
DEV_SIGNALS = r"tgs-viz\backtest\dev_signals.py"
DEV_ODDS, DEV_RATING_ODDS = r"tgs-viz\backtest\dev_odds.py", r"tgs-viz\backtest\dev_rating_odds.py"
ML_DATASET, ML_SCORE = r"tgs-viz\backtest\ml\dataset.py", r"tgs-viz\backtest\ml\score.py"
ML_MODELS = r"tgs-viz\backtest\.dev_cache\ml\models\{basis}\peak_manifest.json"
REPRICE = r"tgs-viz\backtest\ml\reprice.py"
TOKEN = r"tgs-viz\ingest\statsplus_token.py"
PULL_REPORT = r"tgs-viz\ingest\pull_report.py"
CALIBRATE = r"tgs-viz\engine\calibrate.py"
SYNC = r"tgs-viz\ingest\sync_datapoints.py"
EXTRACT_DATA = r"tgs-viz\extract_data.py"


def t_get_ratings():
    no_tok = {"any": [{"no_token": "TGS"}, {"no_token": "BLM"}]}
    csrf = {"all": [no_tok, {"any": [{"all": [{"no_token": "TGS"}, {"no_token": "BLM"}]},
                                     {"input_nonblank": "sessionid"}]}]}
    c = env_cookie()
    steps = [
        step("tok_tgs", "Check the TGS token", py(TOKEN, "--have", "TGS"), kind="probe", set_flag="tok_TGS",
             on_error="ignore"),
        step("tok_blm", "Check the BLM token", py(TOKEN, "--have", "BLM"), kind="probe", set_flag="tok_BLM",
             on_error="ignore"),
        step("cookie", "Browser login", kind="prelude", prelude="cookie_pair", prelude_leagues=["TGS", "BLM"],
             prelude_text={"both": T["ratings.both"], "none": T["ratings.none"], "one": T["ratings.one"]},
             prelude_slugs={"TGS": "tgs", "BLM": "blm"}),
        step("tgs_ratings", "TGS ratings", py(REFRESH, "--statsplus", "--league", "TGS", "--write"),
             "collect", "TGS-ratings", T["ratings.tgs_ratings"], app=True, env=c),
        step("tgs_draft", "TGS draft board", py(DRAFT, "--league", "TGS", "--write"),
             "collect", "TGS-draft", T["ratings.tgs_draft"], app=True, env=c),
        step("tgs_r5", "TGS Rule 5 pool", py(R5, "--league", "TGS", "--write"),
             "collect", "TGS-r5", T["ratings.tgs_r5"], app=True, env=c),
        step("blm_ratings", "BLM ratings", py(REFRESH, "--statsplus", "--league", "BLM", "--slug", "blm", "--write"),
             "collect", "BLM-ratings", T["ratings.blm_ratings"], app=True, env=c),
        step("blm_draft", "BLM draft board", py(DRAFT, "--league", "BLM", "--slug", "blm", "--write"),
             "collect", "BLM-draft", T["ratings.blm_draft"], app=True, env=c),
        step("blm_r5", "BLM Rule 5 pool", py(R5, "--league", "BLM", "--write"),
             "collect", "BLM-r5", T["ratings.blm_r5"], app=True, env=c),
        step("tgs_agecurve", "TGS age curve", py(AGECURVE, "--league", "TGS", "--write"),
             "collect", "TGS-agecurve", T["ratings.agecurve"], app=True, env=c),
        step("blm_agecurve", "BLM age curve", py(AGECURVE, "--league", "BLM", "--write"),
             "collect", "BLM-agecurve", app=True, env=c),
        step("trends", "Rating trends", py(RATINGS_DB, "--export"),
             "collect", "rating-trends", T["ratings.trends"], app=True, env=c),
        step("tgs_devsignals", "TGS dev signals", py(DEV_SIGNALS, "--league", "TGS", "--write"),
             "collect", "TGS-devsignals", T["ratings.devsignals"], app=True, env=c),
        step("blm_devsignals", "BLM dev signals", py(DEV_SIGNALS, "--league", "BLM", "--write"),
             "collect", "BLM-devsignals", app=True, env=c),
        step("tgs_ml_rows", "TGS ML rows", ml(ML_DATASET, "--basis", "TGS", "--score-only", "--write"),
             "collect", "TGS-ml-rows", T["ratings.ml"], env=c),
        step("blm_ml_rows", "BLM ML rows", ml(ML_DATASET, "--basis", "BLM", "--score-only", "--write"),
             "collect", "BLM-ml-rows", env=c),
        step("tgs_ml_score", "TGS ML scores", ml(ML_SCORE, "--league", "TGS", "--write"),
             "collect", "TGS-ml-score", app=True, env=c),
        step("blm_ml_score", "BLM ML scores", ml(ML_SCORE, "--league", "BLM", "--write"),
             "collect", "BLM-ml-score", app=True, env=c),
        step("pull_report", "Data date report", py(PULL_REPORT), "report", None,
             T["ratings.report"] + [{"if_fails": T["ratings.fails"]}], env=c),
    ]
    return task("get_ratings", "Get StatsPlus Ratings",
                "Pulls current ratings for TGS and BLM from StatsPlus, then rebuilds the draft boards, "
                "Rule 5 pools, age curves, rating trends, dev signals and ML dev scores. "
                "A league with no saved token needs your browser cookies.",
                "everyday", steps, leagues=["TGS", "BLM"], bat="Get StatsPlus Ratings.bat",
                requires=["TGS", "BLM"],
                fl=flags(writes_app_data=True, network=True, secret_inputs=True, needs_archive=True),
                time="5 to 15 minutes", inputs=cookie_inputs(no_tok, csrf), banner=T["ratings.banner"],
                finish=fin("fails", ok=T["ratings.end"], fails=T["ratings.end"], exit_ok=None,
                           report_step="pull_report", report_verdict="strict"))


HISTORY_BANNER_RULE5 = [
    " How long: about an hour per run (5 dates, 15 minutes apart; StatsPlus",
    " allows 5 past-date requests a day). Each snapshot waits only when",
    " StatsPlus says it is too soon.",
]
HISTORY_STOP2 = [
    "",
    "  STOPPED (code 2): no StatsPlus login. No token is saved for {league} and",
    "  no browser cookies were given. Nothing was fetched or stored. Paste the",
    "  league's token into StatsPlus Tokens.txt, or run this again and paste",
    "  sessionid and csrftoken.",
]
HISTORY_STOP3_TOKEN_RULE3 = [
    "  Current Token from statsplus.net/{slug} Prefs, paste it into StatsPlus",
    "  Tokens.txt, then run this again.",
]


def t_get_history(ST):
    hist = list(ST.history_settings())
    if not hist:
        return None
    said = say_choices(hist)
    league_in = inp("league", "choice", "League", "The league to pull past ratings for.", required=True,
                    choices=[{"value": lg, "label": (ST.league(lg) or {}).get("name") or lg} for lg in hist],
                    console={"prompt": f"Which league? Type {said}, then press Enter:",
                             "loop_until_valid": True, "invalid_echo": [f" Please type {said}."]})
    ask = {"no_token_input": "league"}
    stop_text = {
        "2": HISTORY_STOP2,
        "3": {"tok": T["history.stop3"] + T["history.stop3_token"] + HISTORY_STOP3_TOKEN_RULE3,
              "": T["history.stop3"] + T["history.stop3_cookie"]},
        "6": T["history.stop6"], "7": T["history.stop7"], "8": T["history.stop8"],
        "9": T["history.stop9"], "10": T["history.stop10"],
    }
    unset = {"STATSPLUS_COOKIE": None}
    steps = [
        step("tok", "Check the token", py(TOKEN, "--have", "{league}"), kind="probe", set_flag="tok",
             on_error="ignore"),
        step("cookie", "Browser login", kind="prelude", prelude="cookie_single",
             prelude_text={"token": T["history.token"], "notoken": T["history.notoken"]}),
        step("history", "Past rating snapshots",
             py(r"tgs-viz\ingest\statsplus_history.py", "--league", "{league}", "--slug", "{slug}", "--write"),
             {"handler": "history_codes"}, "{league}-history", T["history.run"], env=env_cookie(),
             handler_text={"stop": stop_text, "tail": T["history.skipped"] + [""]}),
        step("agecurve", "Age curve", py(AGECURVE, "--league", "{league}", "--write"),
             "collect", "{league}-agecurve", T["history.agecurve"], app=True, env=unset),
        step("trends", "Rating trends", py(RATINGS_DB, "--export"),
             "collect", "rating-trends", T["history.trends"], app=True, env=unset),
        step("devsignals", "Dev signals", py(DEV_SIGNALS, "--league", "{league}", "--write"),
             "collect", "{league}-devsignals", T["history.devsignals"], app=True, env=unset),
        step("ml_rows", "ML rows", ml(ML_DATASET, "--basis", "{league}", "--score-only", "--write"),
             "collect", "{league}-ml-rows", T["history.ml"], env=unset),
        step("ml_score", "ML scores", ml(ML_SCORE, "--league", "{league}", "--write"),
             "collect", "{league}-ml-score", app=True, env=unset),
    ]
    return task("get_history", "Get StatsPlus History",
                "Pulls past ratings (one snapshot every 6 game months) for one league into the ratings "
                "archive, then reruns the age curve, rating trends, dev signals and ML dev scores. "
                "It never changes the current player values.",
                "season", steps, leagues=hist, bat="Get StatsPlus History.bat",
                fl=flags(writes_app_data=True, network=True, secret_inputs=True, long=True, needs_archive=True),
                time="About an hour per run (5 dates, 15 minutes apart; StatsPlus allows 5 past-date requests a day)",
                inputs=[league_in] + cookie_inputs(ask),
                banner=T["history.banner_a"] + HISTORY_BANNER_RULE5 + T["history.banner_b"],
                finish=fin("fails", ok=["", ""], fails=[""] + T["history.fails"] + [""], exit_ok=None))


def t_bank_season():
    actuals, snap = r"tgs-viz\backtest\fetch_actuals.py", r"tgs-viz\backtest\snapshot_projections.py"
    steps = [
        step("tgs_actuals", "TGS season actuals", py(actuals, "--league", "TGS", "--write"),
             "collect", "TGS-actuals", T["bank_season.tgs_actuals"]),
        step("tgs_snapshot", "TGS projection snapshot", py(snap, "--league", "TGS", "--write"),
             "collect", "TGS-snapshot", T["bank_season.tgs_snapshot"]),
        step("blm_actuals", "BLM season actuals", py(actuals, "--league", "BLM", "--slug", "blm", "--write"),
             "collect", "BLM-actuals", T["bank_season.blm_actuals"], fail_echo=T["bank_season.blm_actuals_fail"]),
        step("blm_snapshot", "BLM projection snapshot", py(snap, "--league", "BLM", "--slug", "blm", "--write"),
             "collect", "BLM-snapshot", T["bank_season.blm_snapshot"],
             fail_echo=T["bank_season.blm_snapshot_fail"]),
    ]
    banner = T["bank_season.banner_a"] + [
        "  Mid-season, the actuals step skips that league. The",
        "  projection snapshot still runs.",
    ] + T["bank_season.banner_b"]
    return task("bank_season", "Bank Season",
                "Saves each league's finished season stats and a dated snapshot of the current projections. "
                "Run Get StatsPlus Ratings first. A league that is mid-season is skipped.",
                "season", steps, leagues=["TGS", "BLM"], bat="Bank Season.bat", requires=["TGS", "BLM"],
                fl=flags(network=True), time="1 to 3 minutes", banner=banner,
                finish=fin("fails", ok=T["bank_season.ok"], fails=T["bank_season.fails"], exit_ok=None))


def t_bank_dev(ST):
    ml_steps = ml_retrain_steps()
    for s in ml_steps:
        s["on_error"] = "fail"
    ml_steps[0]["echo"] = T["bank_dev.ml"]
    steps = [
        step("dump_vintages", "Bank new yearly dumps", py(r"tgs-viz\backtest\dump_vintages.py", "--league", "DEV", "--write"),
             echo=T["bank_dev.dump"]),
        step("dev_trends", "DEV trends file", py(RATINGS_DB, "--export", "--league", "DEV"),
             echo=T["bank_dev.trends"], app=True),
        step("dev_value", "Value the new DEV seasons (BLM engine)", dev_price_argv("BLM"),
             echo=T["bank_dev.value"], app=True),
        step("reprice", "Value the new DEV seasons (TGS engine)", dev_price_argv("TGS")),
        step("dev_odds", "DEV odds grid", py(DEV_ODDS, "--write"),
             echo=T["bank_dev.odds"], app=True),
        step("dev_rating_odds", "Make-it odds tables", py(DEV_RATING_ODDS, "--write"),
             echo=T["bank_dev.rating_odds"], app=True),
        step("tgs_devsignals", "TGS dev signals", py(DEV_SIGNALS, "--league", "TGS", "--write"),
             echo=T["bank_dev.devsignals"], app=True),
        step("blm_devsignals", "BLM dev signals", py(DEV_SIGNALS, "--league", "BLM", "--write"), app=True),
    ] + ml_steps + [
        step("manifest", "Register DEV in the app's league list", py(EXTRACT_DATA, "--manifest-only"),
             echo=T["bank_dev.manifest"], app=True),
    ]
    reminders = []
    for lid in ST.extra_leagues():
        name = (ST.league(lid) or {}).get("name") or lid
        reminders.append(f"  {name} still uses its old dev numbers. Run Update {name} to refresh them.")
    ok = reminders + T["bank_dev.ok"][:2] + [
        "  Done. " + NO_RELOAD + " Pick the DEV league."] + T["bank_dev.ok"][2:]
    return task("bank_dev", "Bank Dev Seasons",
                "Banks the DEV seasons you simmed by hand, rebuilds the DEV trends, odds and age curve, retrains "
                "the ML dev models and rescores TGS and BLM. Needs about 13 GB of memory.",
                "dev", steps, leagues=["DEV", "TGS", "BLM"], bat="Bank Dev Seasons.bat",
                requires=["DEV", "TGS", "BLM"],
                fl=flags(heavy=True, long=True, writes_app_data=True, needs_archive=True),
                locks=["dumps.DEV"], time="Hours (retrains the ML models; needs about 13 GB of memory)",
                banner=T["bank_dev.banner"],
                finish=fin("failfast", ok=ok, fail=T["bank_dev.fail"], exit_ok=0, exit_fail=1))


def dev_price_argv(basis):
    """The DEV re-price of Bank Dev Seasons on one basis. BLM: agecurve_fit,
    which also rewrites the DEV age curve that every league's path uses. TGS:
    ml/reprice.py (its prices live in .dev_cache/ml/waa_TGS)."""
    if basis == "BLM":
        return py(AGECURVE, "--league", "DEV", "--calib", "BLM", "--no-guard", "--write")
    return py(REPRICE, "--calib", "TGS")


def dev_price_steps(ST, bases):
    """What a retrain on these bases runs before its ML steps, in Bank Dev
    Seasons order. First the DEV re-price on each basis: a recalibration gives
    the DEV prices a new tag, and dataset.py stops until DEV is priced with it.
    The odds grid, the Make-it odds tables and the dev signals read the BLM
    prices, so a BLM re-price reruns them, the dev signals for every league
    that shows them (TGS, BLM and each extra league). A step for a league the
    card trains stops the card when it fails; a step for another league
    collects its failure and the card goes on."""
    out = []
    if "BLM" in bases:
        out.append(step("dev_value", "Value the DEV seasons (BLM engine) and rebuild the DEV age curve",
                        dev_price_argv("BLM"), app=True))
    if "TGS" in bases:
        out.append(step("reprice", "Value the DEV seasons (TGS engine)", dev_price_argv("TGS")))
    if "BLM" in bases:
        out += [step("dev_odds", "DEV odds grid", py(DEV_ODDS, "--write"), app=True),
                step("dev_rating_odds", "Make-it odds tables", py(DEV_RATING_ODDS, "--write"), app=True)]
        shown = [lg for lg in ("TGS", "BLM") if lg in ST.leagues()] + list(ST.extra_leagues())
        for lg in shown:
            own = lg in bases
            out.append(step(f"{lg.lower()}_devsignals", f"{lg} dev signals", py(DEV_SIGNALS, "--league", lg, "--write"),
                            "fail" if own else "collect", None if own else f"{lg}-devsignals", app=True))
    return out


def ml_extra_steps(leagues):
    """ML rows, then ML scores, of the extra leagues a retrained basis scores."""
    out = []
    for x in leagues:
        out.append(step(f"{x.lower()}_ml_rows", f"{x} ML rows", ml(ML_DATASET, "--basis", x, "--score-only", "--write"),
                        "collect", f"{x}-ml-rows"))
        out.append(step(f"{x.lower()}_ml_score", f"{x} ML scores", ml(ML_SCORE, "--league", x, "--write"),
                        "collect", f"{x}-ml-score", app=True))
    return out


def ml_retrain_steps(bases=("TGS", "BLM")):
    """The 10 ML steps of Bank Dev Seasons, in bat order."""
    peak, path = r"tgs-viz\backtest\ml\peak.py", r"tgs-viz\backtest\ml\path.py"
    predict = r"tgs-viz\backtest\ml\predict.py"
    out = [step(f"{b.lower()}_ml_dataset", f"{b} ML training rows", ml(ML_DATASET, "--basis", b, "--write")) for b in bases]
    for b in bases:
        out.append(step(f"{b.lower()}_ml_peak", f"{b} ML peak model", ml(peak, "fit-final", "--basis", b)))
        out.append(step(f"{b.lower()}_ml_path", f"{b} ML path model", ml(path, "fit-final", "--basis", b)))
    out += [step(f"{b.lower()}_ml_check", f"{b} ML model check", ml(predict, "check", "--basis", b)) for b in bases]
    out += [step(f"{b.lower()}_ml_score", f"{b} ML scores", ml(ML_SCORE, "--league", b, "--write"), app=True)
            for b in bases]
    return out


def calibrate_argv(lg, dumps):
    d = rf"tgs-viz\engine\calib\{lg}"
    return py(CALIBRATE, "--csv-dir", d, "--dumps", dumps, "--ratings-dir", d,
              "--json", rf"{d}\constants-latest.json", "--archive-dir", d)


def fit_steps(lg, promote=True, export_policy="ignore", extract_first=False):
    e = r"tgs-viz\engine"
    fits = [
        step("hitter_tails", "Hitter tails fit", py(rf"{e}\hitter_tails_fit.py", "--league", lg)),
        step("fielding_curves", "Fielding curves fit", py(rf"{e}\fielding_curves_fit.py", "--league", lg)),
        step("currency", "Currency fit", py(rf"{e}\currency_fit.py", "--league", lg)),
        step("scurve", "S-curve preview", py(rf"{e}\scurve_fit.py", "--league", lg), "ignore"),
    ]
    if promote:
        fits.append(step("promote_scurves", "S-curve promotion", py(rf"{e}\promote_scurves.py", "--league", lg), "ignore"))
    return fits


def extract_steps(lg, suffix=""):
    e = r"tgs-viz\engine"
    return [step(f"extract_sheet{suffix}", f"Read back the {lg} hitter sheet", py(rf"{e}\extract_sheet.py", lg), "ignore"),
            step(f"extract_pitchers{suffix}", f"Read back the {lg} pitcher sheet", py(rf"{e}\extract_pitchers.py", lg),
                 "ignore")]


def t_grind(ST, lg):
    ver = "26" if lg == "TGS" else "27"
    dumps = "{saved_games:26}/*tgs*.lg" if lg == "TGS" else "{saved_games:27}/0blm*.lg"
    key = "grind_tgs" if lg == "TGS" else "grind_blm"
    slug = ["--slug", "blm"] if lg == "BLM" else []
    const = rf"tgs-viz\engine\calib\{lg}\constants-latest.json"
    steps = [
        gate(input="ootp_ready"),
        step("winsim", f"Sim {lg} clones", py(WINSIM, "--league", lg, "--runs", "{runs}"), "stopafter",
             fail_echo=T["grind.winsim_fail"]),
        step("calibrate", "Calibrate from the clone dumps", calibrate_argv(lg, dumps), echo=T[f"{key}.recal"]),
        excel_check("excel", f"The Sheets {lg}"),
        step("sync", f"Move the constants into The Sheets {lg}",
             py(SYNC, "--league", lg, "--calib", const, "--write", "--yes")),
    ] + fit_steps(lg, promote=(lg == "TGS")) + extract_steps(lg) + [
        step("agecurve", "Age curve", py(AGECURVE, "--league", lg, "--write"), "ignore", app=True),
        step("export_calibration", "Calibration page data", py(r"tgs-viz\engine\export_calibration.py", "--league", lg, "--write"),
             "ignore", app=True),
        step("refresh", "Rebuild the app data from the cached pull",
             py(REFRESH, "--statsplus", "--from-cache", "--league", lg, *slug, "--write"), app=True),
        step("cleanup", "Delete the spent clone saves", py(CLEANUP, "--league", lg, "--junk", "--yes"), "ignore"),
    ]
    cycle = [s.replace("simming 10 clones (~100 seasons)", "simming {runs} clones (~{seasons} seasons)")
             for s in T[f"{key}.cycle"]]
    if lg == "TGS":
        ready = "OOTP 26 is open inside a league other than Baseline, and nothing else needs the mouse."
        stopped, fail = T["grind.stopped"], T["grind.fail"]
    else:
        ready = 'OOTP 27 is open inside a league other than "6", and nothing else needs the mouse.'
        stopped, fail = T["grind_blm.stopped"], T["grind_blm.fail"]
    return task(key, f"Grind {lg}",
                f"Sims {lg} clone leagues in OOTP {ver}, then recalibrates the constants, sheets and app data, "
                "and deletes the spent clone saves. Then it starts the next cycle.",
                "calibration", steps, leagues=[lg], bat=f"Grind {lg}.bat", requires=[lg],
                fl=flags(endless=True, drives_ootp=True, needs_excel_closed=True, heavy=True, writes_app_data=True,
                         needs_archive=True),
                locks=["ootp", f"clones.{lg}"], time="Runs until you stop it; about 75 minutes per cycle",
                inputs=[ootp_ready(ready), runs_input()], banner=T[f"{key}.banner"],
                loop={"from_step": "winsim", "cycle_echo": cycle},
                finish=fin("failfast", fail=fail, stopped=stopped, exit_fail=1, exit_stopped=1))


def t_recalibrate_tgs():
    const = r"tgs-viz\engine\calib\TGS\constants-latest.json"
    sync = py(SYNC, "--league", "TGS", "--calib", const, "--write")
    cleanup = py(CLEANUP, "--league", "TGS", "--junk")
    steps = [
        gate(),
        step("calibrate", "Calibrate from the clone dumps", calibrate_argv("TGS", "{saved_games:26}/*tgs*.lg")),
        excel_check("excel", "The Sheets TGS"),
        step("sync", "Move the constants into The Sheets TGS", sync, job=sync_job(sync, "The Sheets TGS")),
    ] + fit_steps("TGS") + [
        step("export_calibration", "Calibration page data",
             py(r"tgs-viz\engine\export_calibration.py", "--league", "TGS", "--write"), app=True),
    ] + extract_steps("TGS") + [
        step("refresh", "Rebuild the app data from the cached pull",
             py(REFRESH, "--statsplus", "--from-cache", "--league", "TGS", "--write"), app=True),
        step("cleanup", "Delete the clone saves", cleanup, "ignore", echo=T["recal_tgs.cleanup"],
             job=cleanup_job(cleanup)),
    ]
    ok = replace_line(T["recal_tgs.ok"], T["recal_tgs.ok"][2], [
        "  Done. " + NO_RELOAD + " Your Excel sheets recalc with the", T["recal_tgs.ok"][2]])
    return task("recalibrate_tgs", "Recalibrate TGS",
                "Computes the TGS regression constants from the clone sims on disk, moves them into The Sheets "
                "TGS (you confirm the changes first), refits the fitted layers and rebuilds the app data.",
                "calibration", steps, leagues=["TGS"], bat="Recalibrate TGS.bat", requires=["TGS"],
                fl=flags(needs_excel_closed=True, writes_app_data=True, needs_archive=True),
                locks=["clones.TGS"], time="1 to 3 minutes plus your answers", banner=T["recal_tgs.banner"],
                finish=fin("failfast", ok=ok, fail=T["recal.fail"], exit_ok=0, exit_fail=1))


def t_recalibrate_blm():
    inputs_dir = r"tgs-viz\engine\calib\BLM\metadata_inputs"
    meta = r"tgs-viz\engine\calib\BLM\metadata-latest.json"
    const = r"tgs-viz\engine\calib\BLM\constants-latest.json"
    mi = r"tgs-viz\ingest\metadata_inputs.py"
    cleanup = py(CLEANUP, "--league", "BLM", "--junk")
    steps = [
        gate(),
        step("metadata_auto", "Metadata inputs from StatsPlus",
             py(mi, "--league", "BLM", "--out", inputs_dir, "--stage", "auto"), echo=T["recal_blm.a1"]),
        gate("paste_reminder",
             text="Paste 'SP Data' (as starter) and 'RP Data' (as reliever) into The Sheets BLM\\25 Metadata.xlsx, "
                  "save, and close Excel.",
             echo=T["recal_blm.reminder"]),
        step("metadata_roles", "Your SP/RP paste",
             py(mi, "--league", "BLM", "--out", inputs_dir, "--stage", "roles", "--accept-paste"), echo=T["recal_blm.a2"]),
        step("metadata_calibrate", "Metadata data points",
             py(r"tgs-viz\engine\metadata_calibrate.py", "--inputs-dir", inputs_dir, "--json", meta,
                "--derived-out-values"),     # out values from the league's own run values (docs/phase2/out_values.md)
             echo=T["recal_blm.a3"]),
        step("calibrate", "Regressions from the BLM clone archive",
             calibrate_argv("BLM", "{saved_games:27}/0blm*.lg"), echo=T["recal_blm.b"]),
        excel_check("excel", "The Sheets BLM"),
        step("sync", "Move the metadata and regressions into The Sheets BLM",
             py(SYNC, "--league", "BLM", "--calib", const, "--metadata-calib", meta, "--write", "--yes"),
             echo=T["recal_blm.sync"]),
    ] + fit_steps("BLM") + [
        step("export_calibration", "Calibration page data",
             py(r"tgs-viz\engine\export_calibration.py", "--league", "BLM", "--write"), app=True),
    ] + extract_steps("BLM") + [
        step("refresh", "Rebuild the app data from the cached pull",
             py(REFRESH, "--statsplus", "--from-cache", "--league", "BLM", "--slug", "blm", "--write"),
             echo=T["recal_blm.refresh"], app=True),
        step("cleanup", "Delete the clone saves", cleanup, "ignore", echo=T["recal_blm.cleanup"],
             job=cleanup_job(cleanup)),
    ]
    ok = T["recal_blm.ok"][:2] + ["  Done. " + NO_RELOAD] + T["recal_blm.ok"][2:]
    return task("recalibrate_blm", "Recalibrate BLM",
                "Run this only after the BLM season ends: the metadata step refuses in game months 4 to 9. "
                "Builds the BLM metadata from StatsPlus and your SP/RP paste, recalibrates the regressions, "
                "moves both into The Sheets BLM and rebuilds the app data.",
                "season", steps, leagues=["BLM"], bat="Recalibrate BLM.bat", requires=["BLM"],
                fl=flags(network=True, needs_excel_closed=True, writes_app_data=True, needs_archive=True),
                locks=["clones.BLM"], time="A few minutes plus your SP/RP paste", banner=T["recal_blm.banner"],
                finish=fin("failfast", ok=ok, fail=T["recal_blm.fail"], exit_ok=0, exit_fail=1))


def t_sim_dev():
    steps = [
        gate(input="ootp_ready"),
        step("winsim", "Sim the DEV seasons", py(WINSIM, "--league", "DEV", "--sim", "--years", "{years}"),
             echo=T["sim_dev.sim"]),
        step("dump_script", "Check the banking script", kind="exists_check",
             path=r"tgs-viz\backtest\dump_vintages.py", echo=T["sim_dev.bank"], missing_echo=T["sim_dev.missing"]),
        step("dump_vintages", "Bank the yearly dumps", py(r"tgs-viz\backtest\dump_vintages.py", "--league", "DEV", "--write")),
        step("dev_trends", "DEV trends file", py(RATINGS_DB, "--export", "--league", "DEV"),
             echo=T["sim_dev.trends"], app=True),
        step("manifest", "Register DEV in the app's league list", py(EXTRACT_DATA, "--manifest-only"),
             echo=T["sim_dev.manifest"], app=True),
    ]
    ok = T["sim_dev.ok"][:2] + ["  Done. " + NO_RELOAD + " Pick the DEV league."] + T["sim_dev.ok"][2:]
    return task("sim_dev", "Sim Dev League",
                "Sims DEV TESTS in OOTP 27 for the number of seasons you choose, then banks the yearly dumps "
                "and rebuilds the DEV trends file.",
                "dev", steps, leagues=["DEV"], bat="Sim Dev League.bat", requires=["DEV"],
                fl=flags(drives_ootp=True, long=True, writes_app_data=True, needs_archive=True),
                locks=["ootp", "dumps.DEV"], time="Depends on OOTP sim speed",
                inputs=[inp("years", "text", "Seasons to sim", "How many seasons (1 to 50).", default="5",
                            fmt="int", min=1, max=50, from_argv=1),
                        ootp_ready("OOTP 27 is open inside a league (any league; the main menu is not enough). "
                                   "In DEV TESTS, Export CSV files after each simulated season is on.")],
                banner=T["sim_dev.banner"],
                finish=fin("failfast", ok=ok, fail=T["sim_dev.fail"], exit_ok=0, exit_fail=1))


def t_sync_metadata():
    tgs_c = r"tgs-viz\engine\calib\TGS\constants-latest.json"
    blm_c = r"tgs-viz\engine\calib\BLM\constants-latest.json"
    meta = r"tgs-viz\engine\calib\BLM\metadata-latest.json"
    s_tgs = py(SYNC, "--league", "TGS", "--calib", tgs_c, "--write")
    s_blm_meta = py(SYNC, "--league", "BLM", "--calib", blm_c, "--metadata-calib", meta, "--write")
    s_blm = py(SYNC, "--league", "BLM", "--calib", blm_c, "--write")
    steps = [
        excel_check("excel_tgs", "The Sheets TGS"),
        step("sync_tgs", "Sync The Sheets TGS", s_tgs, job=sync_job(s_tgs, "The Sheets TGS")),
        excel_check("excel_blm", "The Sheets BLM"),
        step("sync_blm_meta", "Sync The Sheets BLM", s_blm_meta, when={"exists": meta},
             job=sync_job(s_blm_meta, "The Sheets BLM")),
        step("sync_blm", "Sync The Sheets BLM", s_blm, when={"not": {"exists": meta}},
             job=sync_job(s_blm, "The Sheets BLM")),
    ] + extract_steps("TGS", "_tgs") + extract_steps("BLM", "_blm")
    ok = T["sync.ok"][:3] + ["  data. " + NO_RELOAD] + T["sync.ok"][3:]
    return task("sync_metadata", "Sync Metadata",
                "Copies the metadata constants into the Data Points tabs of The Sheet Hitters and Pitchers for "
                "TGS and BLM. It shows every change and asks before it writes.",
                "season", steps, leagues=["TGS", "BLM"], bat="Sync Metadata.bat", requires=["TGS", "BLM"],
                fl=flags(needs_excel_closed=True), time="Under a minute plus your answers",
                banner=T["sync.banner"],
                finish=fin("failfast", ok=ok, fail=T["sync.fail"], exit_ok=0, exit_fail=1))


def t_dispersal(ST):
    orgs = ",".join((ST.league("TGS") or {}).get("dispersal_orgs") or [])
    steps = [step("draft", "Dispersal draft board", py(DRAFT, "--league", "TGS", "--orgs", "{orgs}", "--write"),
                  app=True)]
    return task("dispersal_board", "Update Dispersal Board",
                "Builds the TGS dispersal draft board from the cached StatsPlus pull: every player in the folding "
                "orgs. Add each drafted player's name to dispersal_drafted.txt and run it again.",
                "everyday", steps, leagues=["TGS"], bat="Update Dispersal Board.bat", requires=["TGS"],
                fl=flags(network=True, writes_app_data=True), time="Under a minute",
                inputs=[inp("orgs", "text", "Folding orgs", "Org names, separated by commas.", default=orgs)],
                banner=T["dispersal.banner"],
                finish=fin("failfast", ok=T["dispersal.ok"] + [
                    "  Done. " + NO_RELOAD + " The Draft tab is now the dispersal pool."],
                    fail=T["dispersal.fail"], exit_ok=None, exit_fail=None))


def t_draft_board():
    steps = [
        step("tgs", "TGS draft board", py(DRAFT, "--league", "TGS", "--write"), "collect", "TGS", T["draft.tgs"], app=True),
        step("blm", "BLM draft board", py(DRAFT, "--league", "BLM", "--slug", "blm", "--write"), "collect", "BLM",
             T["draft.blm"], app=True),
    ]
    ok = T["draft.ok"][:2] + ["  Done. " + NO_RELOAD + " Switch leagues to see each board."] + T["draft.ok"][2:]
    return task("draft_board", "Update Draft Board",
                "Builds the TGS and BLM draft boards: the class from StatsPlus (or your OOTP draft-pool export "
                "when StatsPlus does not answer), the ratings from the StatsPlus pull.",
                "everyday", steps, leagues=["TGS", "BLM"], bat="Update Draft Board.bat", requires=["TGS", "BLM"],
                fl=flags(network=True, writes_app_data=True), time="1 to 2 minutes", banner=T["draft.banner"],
                finish=fin("fails", ok=ok, fails=T["draft.fails"], exit_ok=None))


def t_ootp_tools():
    out = []
    out.append(task("ootp_check_26", "Check OOTP (26)",
                    "Lists the windows the tool can see and saves a screenshot of OOTP 26 to ootp\\winsim_grab.png. "
                    "It brings OOTP to the front and clicks nothing.",
                    "ootp", [
                        step("list_windows", "List the windows", py(WINSIM, "--game", "26", "--list-windows"), "ignore",
                             echo=T["o1.list"]),
                        step("grab", "Screenshot of OOTP", py(WINSIM, "--game", "26", "--grab"), "ignore", echo=T["o1.grab"]),
                    ], bat="ootp/1 - Check OOTP (26).bat", locks=["ootp"], time="Seconds", banner=T["o1.banner"],
                    finish=fin("fails", ok=T["o1.ok"], fails=T["o1.ok"], exit_ok=None)))
    out.append(task("ootp_grab_menu_26", "Grab a menu (26)",
                    "After you press Start, you have 6 seconds to open the menu in OOTP. Then it saves a screenshot.",
                    "ootp", [
                        gate(job_message="After you press Start, you have 6 seconds to open the menu in OOTP."),
                        step("grab", "Screenshot of the open menu", py(WINSIM, "--game", "26", "--grab", "--delay", "6"),
                             "ignore"),
                    ], bat="ootp/2 - Grab a menu (26).bat", fl=flags(drives_ootp=True), locks=["ootp"],
                    time="About 10 seconds", banner=T["o2.banner"],
                    finish=fin("fails", ok=T["o2.ok"], fails=T["o2.ok"], exit_ok=None)))
    out.append(task("sim_tgs_preview", "Sim TGS (preview)",
                    "Shows the TGS clone sim plan. Clones nothing and clicks nothing.",
                    "calibration", [step("preview", "Show the plan", py(WINSIM, "--league", "TGS", "--runs", "1", "--dry-run"),
                                         "ignore")],
                    bat="ootp/3 - Sim TGS (preview).bat", requires=["TGS"], fl=flags(read_only=True), time="Seconds",
                    banner=T["o3.banner"], finish=fin("fails", ok=T["o3.ok"], fails=T["o3.ok"], exit_ok=None)))
    out.append(task("sim_tgs", "Sim TGS",
                    "Clones the TGS Baseline league and auto-plays each clone in OOTP 26. Then run Recalibrate TGS.",
                    "calibration", [
                        gate(input="ootp_ready"),
                        step("winsim", "Sim TGS clones", py(WINSIM, "--league", "TGS", "--runs", "{runs}"), "ignore"),
                    ], bat="ootp/4 - Sim TGS.bat", requires=["TGS"], fl=flags(drives_ootp=True, long=True),
                    locks=["ootp", "clones.TGS"], time="About 75 minutes",
                    inputs=[ootp_ready("OOTP 26 is open inside a league other than Baseline, and nothing else needs "
                                       "the mouse."), runs_input()],
                    banner=T["o4.banner"], finish=fin("fails", ok=T["o4.ok"], fails=T["o4.ok"], exit_ok=None)))
    out.append(task("ootp_test_year_26", "Test the year picker (26)",
                    "Opens Play, Specified Date in the loaded OOTP 26 league and tries to set the year, then stops "
                    "and saves screenshots. It never sims.",
                    "ootp", [
                        gate(input="ootp_ready"),
                        step("test_year", "Year picker test", py(WINSIM, "--league", "TGS", "--test-year"), "ignore"),
                    ], bat="ootp/TEST year picker.bat", requires=["TGS"], fl=flags(drives_ootp=True), locks=["ootp"],
                    time="Under a minute",
                    inputs=[ootp_ready("OOTP 26 is open with a league loaded, and nothing else needs the mouse.")],
                    banner=T["ot.banner"], finish=fin("fails", ok=T["ot.ok"], fails=T["ot.ok"], exit_ok=None)))
    return out


# ---------------------------------------------------------------- generated per-league tasks

RG_BANNER = [
    "",
    " ===============================================",
    "   Update {name}  (OOTP {ootp_version} save, {basis} settings)",
    " ===============================================",
    "",
    " BEFORE running this: open {ootp_save} in OOTP and export the database",
    " to CSV again (the same export as the first time). It goes to",
    "   saved_games\\{ootp_save}.lg\\import_export\\csv",
    " Optional: for signing demands on the international board, also export",
    " OOTP's International Amateur Free Agents screen to its import_export folder.",
    "",
    " What this does: prices every player with {basis}'s engine settings, builds",
    " the draft board (this year's draft class) and the international list,",
    " saves this export as a snapshot (so growth and rating trends build up as",
    " you sim), then the dev signals and the ML dev chances (the {basis}-trained",
    " model). Running it again on the same export replaces that snapshot.",
    "",
]


def fill_static(lines, values):
    out = []
    for line in lines:
        for k, v in values.items():
            line = line.replace("{" + k + "}", str(v))
        out.append(line)
    return out


def t_update_statsplus(ST, lg):
    lid = lg["id"]
    slug = ST.slug(lid)
    basis = lg.get("basis") or lid
    calib = ["--calib", basis] if basis != lid else []
    c = env_cookie()
    steps = [
        step("tok", "Check the token", py(TOKEN, "--have", lid), kind="probe", set_flag="tok", on_error="ignore"),
        step("cookie", "Browser login", kind="prelude", prelude="cookie_single",
             prelude_text={"token": [" Using the saved " + lid + " StatsPlus token. No browser cookies needed."],
                           "notoken": [" No StatsPlus token is saved for " + lid + ". Using your browser cookies."]}),
        step("ratings", f"{lid} ratings", py(REFRESH, "--statsplus", "--league", lid, "--slug", slug, *calib, "--write"),
             "collect", f"{lid}-ratings", app=True, env=c),
        step("draft", f"{lid} draft board", py(DRAFT, "--league", lid, "--slug", slug, *calib, "--write"),
             "collect", f"{lid}-draft", app=True, env=c),
    ]
    if lg.get("ootp_save"):
        steps.append(step("r5", f"{lid} Rule 5 pool", py(R5, "--league", lid, "--write"), "collect", f"{lid}-r5",
                          app=True, env=c))
    if basis == lid:
        steps.append(step("agecurve", f"{lid} age curve", py(AGECURVE, "--league", lid, "--write"), "collect",
                          f"{lid}-agecurve", app=True, env=c))
    steps += [
        step("trends", "Rating trends", py(RATINGS_DB, "--export", "--league", lid), "collect", "rating-trends",
             app=True, env=c),
        step("devsignals", f"{lid} dev signals", py(DEV_SIGNALS, "--league", lid, "--write"), "collect",
             f"{lid}-devsignals", app=True, env=c),
        step("ml_rows", f"{lid} ML rows", ml(ML_DATASET, "--basis", lid, "--score-only", "--write"), "collect",
             f"{lid}-ml-rows", env=c),
        step("ml_score", f"{lid} ML scores", ml(ML_SCORE, "--league", lid, "--write"), "collect", f"{lid}-ml-score",
             app=True, env=c),
    ]
    # A wizard-added league priced on another league's calibration (SSB on BLM) has no agecurve step, so
    # its latest pull's engine-WAA cache (.waa_cache, the basis fingerprint) is built here; ml/dataset.py
    # reads it. --cache-only runs the engine on the vintages and writes no age curve. TGS / BLM / RG keep
    # the steps their bats pin.
    if basis != lid and lid not in defaults_league_ids(ST):
        i = next(k for k, x in enumerate(steps) if x["id"] == "ml_rows")
        steps.insert(i, step("waa_cache", f"{lid} engine WAA cache",
                             py(AGECURVE, "--league", lid, "--calib", basis, "--cache-only"), "collect",
                             f"{lid}-waa-cache", env=c))
    # The models are the author's files (backtest/ml/install_models.py), not trained on the Mac. A
    # wizard-added league with no models installed for its basis skips the scoring step instead of
    # failing it. TGS / BLM / RG keep the step their bats pin (test_bat_equivalence).
    if lid not in defaults_league_ids(ST):
        ms = next(x for x in steps if x["id"] == "ml_score")
        ms["when"] = {"exists": ML_MODELS.format(basis=basis)}
        ms["skip_echo"] = [f" No {basis} models installed: skipping {lid} ML scores "
                           "(install the author's files with backtest/ml/install_models.py)."]
    # A wizard-added league's manifest entry (its pages: draft, contracts, ...) was built once, at
    # New League time. Rebuild its datasets/features from the files this run wrote, so a page whose
    # files appeared later (SSB's draft boards) is offered without a hand edit. TGS / BLM keep the
    # steps their bats pin (test_bat_equivalence).
    if lid not in defaults_league_ids(ST):
        steps.append(step("manifest", "Refresh the app's page list", py(NEW_LEAGUE, "refresh-manifest", "--league", lid),
                          "collect", f"{lid}-manifest", app=True))
    steps.append(step("pull_report", "Data date report", py(PULL_REPORT, "--leagues", lid), "report", env=c))
    headers(steps)
    name = lg.get("name") or lid
    return task(f"update.{lid}", f"Update {name}",
                f"Pulls current {name} ratings from StatsPlus, then rebuilds its draft board, rating trends, "
                "dev signals and ML dev scores. With no saved token it needs your browser cookies.",
                "leagues", steps, leagues=[lid], requires=[lid],
                fl=flags(network=True, secret_inputs=True, writes_app_data=True, needs_archive=True),
                time="5 to 10 minutes", inputs=cookie_inputs({"no_token": lid}),
                finish=fin("fails", ok=[""], fails=["", "  Steps that did not update:{fails}",
                                                     "  (each one said why above)"],
                           exit_ok=None, report_step="pull_report", report_verdict="strict"))


def t_draft_league(ST, lg):
    """The draft board alone for a wizard-added StatsPlus league: the pick list (/draft, read fresh)
    and the pool (/draftpool/, at most once per in-game day) against the last ratings pull. For use
    between picks while a draft runs; Update <league> refreshes the ratings themselves."""
    lid = lg["id"]
    slug = ST.slug(lid)
    basis = lg.get("basis") or lid
    calib = ["--calib", basis] if basis != lid else []
    c = env_cookie()
    steps = [
        step("tok", "Check the token", py(TOKEN, "--have", lid), kind="probe", set_flag="tok", on_error="ignore"),
        step("cookie", "Browser login", kind="prelude", prelude="cookie_single",
             prelude_text={"token": [" Using the saved " + lid + " StatsPlus token. No browser cookies needed."],
                           "notoken": [" No StatsPlus token is saved for " + lid + ". Using your browser cookies."]}),
        step("draft", f"{lid} draft board", py(DRAFT, "--league", lid, "--slug", slug, *calib, "--write"),
             "collect", f"{lid}-draft", app=True, env=c),
        step("manifest", "Refresh the app's page list", py(NEW_LEAGUE, "refresh-manifest", "--league", lid),
             "collect", f"{lid}-manifest", app=True),
    ]
    headers(steps)
    name = lg.get("name") or lid
    return task(f"draft.{lid}", f"Update {name} Draft Board",
                f"Rebuilds the {name} draft board with the latest picks from StatsPlus, priced on the last "
                f"ratings pull. Quick: use it between picks. Update {name} refreshes the ratings.",
                "leagues", steps, leagues=[lid], requires=[lid],
                fl=flags(network=True, secret_inputs=True, writes_app_data=True),
                time="under a minute", inputs=cookie_inputs({"no_token": lid}),
                finish=fin("fails", ok=[""], fails=["", "  Steps that did not update:{fails}",
                                                     "  (each one said why above)"], exit_ok=None))


def t_bank_season_league(ST, lg):
    """Season end for one wizard-added StatsPlus league (Phase 2 row 10 decision, 2026-10-03):
    bank the finished season's actuals, snapshot the projections, then the fielding referee on
    that season (a report: it changes no number, so its failure never fails the task). TGS and
    BLM keep the combined Bank Season task."""
    lid = lg["id"]
    slug = ST.slug(lid)
    basis = lg.get("basis") or lid
    actuals, snap = r"tgs-viz\backtest\fetch_actuals.py", r"tgs-viz\backtest\snapshot_projections.py"
    steps = [
        step("actuals", f"{lid} season actuals", py(actuals, "--league", lid, "--slug", slug, "--write"),
             "collect", f"{lid}-actuals"),
        step("snapshot", f"{lid} projection snapshot", py(snap, "--league", lid, "--slug", slug, "--write"),
             "collect", f"{lid}-snapshot"),
        step("referee", "Fielding check (real season vs the fielding curves)",
             py(r"tgs-viz\backtest\referee_fielding.py", "--league", lid, "--basis", basis,
                "--sample", "actuals:latest:auto"), "ignore"),
    ]
    headers(steps)
    name = lg.get("name") or lid
    return task(f"bank_season.{lid}", f"Bank {name} season",
                f"Saves {name}'s finished season stats and a dated snapshot of the current projections, then "
                "checks the fielding curves against that season. Run it after the season ends and after a "
                f"ratings update. A season still in progress is skipped.",
                "season", steps, leagues=[lid], requires=[lid], fl=flags(network=True), time="1 to 3 minutes",
                finish=fin("fails", ok=[""], fails=["", "  Steps that did not finish:{fails}",
                                                     "  (each one said why above)"], exit_ok=None))


def t_update_local(ST, lg):
    lid = lg["id"]
    name = lg.get("name") or lid
    vals = {"name": name, "ootp_save": lg.get("ootp_save") or "", "ootp_version": lg.get("ootp_version") or "",
            "basis": lg.get("basis") or "BLM"}
    steps = [
        step("players", "Players, draft board, internationals, snapshot, rating trends",
             py(r"tgs-viz\ingest\export_league.py", "--league", lid, "--name", vals["name"], "--save", vals["ootp_save"],
                "--game", vals["ootp_version"], "--calib", vals["basis"], "--write"),
             "collect", "players", T["rg.players"], app=True),
        step("devsignals", "Dev signals", py(DEV_SIGNALS, "--league", lid, "--write"), "collect", "dev-signals",
             T["rg.devsignals"], app=True),
        step("ml_rows", "ML rows", ml(ML_DATASET, "--basis", lid, "--score-only", "--write"), "collect", "ml-rows",
             T["rg.ml"]),
        step("ml_score", "ML scores", ml(ML_SCORE, "--league", lid, "--write"), "collect", "ml-score", app=True),
    ]
    ok = [T["rg.fails"][0], f'  Done. {NO_RELOAD} Pick "{name}" in the league menu.', T["rg.fails"][-1]]
    return task(f"update.{lid}", f"Update {name}",
                f"Reads the CSV export of the {vals['ootp_save']} save (OOTP {vals['ootp_version']}), prices every "
                f"player with {vals['basis']}'s settings, then rebuilds the dev signals and ML dev scores. "
                "Export the database to CSV in OOTP first.",
                "leagues", steps, leagues=[lid], bat="Update Regular Game.bat" if lid == "RG" else None,
                requires=[lid], fl=flags(writes_app_data=True, needs_archive=True), time="1 to 3 minutes",
                banner=fill_static(RG_BANNER, vals),
                finish=fin("fails", ok=ok, fails=T["rg.fails"], exit_ok=None))


def dev_update_steps(ST, lid):
    if lid == "DEV":
        reg = step("manifest", "Register in the app's league list",
                   py(NEW_LEAGUE, "register-manifest", "--league", lid), app=True)
    else:
        reg = step("manifest", "Register in the app's league list",
                   py(NEW_LEAGUE, "register-manifest", "--league", lid), app=True)
    return [
        step("dump_vintages", "Bank new yearly dumps", py(r"tgs-viz\backtest\dump_vintages.py", "--league", lid, "--write")),
        step("trends", "Trends file", py(RATINGS_DB, "--export", "--league", lid), app=True),
        reg,
    ]


def t_update_dev(ST, lg):
    lid = lg["id"]
    name = lg.get("name") or lid
    steps = headers(dev_update_steps(ST, lid))
    return task(f"update.{lid}", f"Update {name}" if lid != "DEV" else "Update DEV",
                f"Banks the yearly dumps of {name} that are not banked yet and rebuilds its trends file. "
                "No simming.",
                "dev", steps, leagues=[lid], requires=[lid], fl=flags(writes_app_data=True, needs_archive=True),
                locks=[f"dumps.{lid}"], time="About 20 seconds per new season",
                finish=fin("failfast", exit_ok=0, exit_fail=1))


def t_sim_dev_other(ST, lg):
    lid = lg["id"]
    name = lg.get("name") or lid
    ver = lg.get("ootp_version") or "27"
    prof = lg.get("ootp_profile") or {}
    years = str(prof.get("years") or 5)
    steps = [gate(input="ootp_ready"),
             step("winsim", f"Sim {name}", py(WINSIM, "--league", lid, "--sim", "--years", "{years}"))
             ] + dev_update_steps(ST, lid)
    headers(steps)
    return task(f"sim_dev.{lid}", f"Sim {name}",
                f"Sims {name} in OOTP {ver} for the number of seasons you choose, then banks the yearly dumps "
                "and rebuilds its trends file.",
                "dev", steps, leagues=[lid], requires=[lid],
                fl=flags(drives_ootp=True, long=True, writes_app_data=True, needs_archive=True),
                locks=["ootp", f"dumps.{lid}"], time="Depends on OOTP sim speed",
                inputs=[inp("years", "text", "Seasons to sim", "How many seasons (1 to 50).", default=years, fmt="int",
                            min=1, max=50, from_argv=1),
                        ootp_ready(f"OOTP {ver} is open inside a league (the main menu is not enough), and nothing "
                                   "else needs the mouse.")],
                finish=fin("failfast", exit_ok=0, exit_fail=1))


def t_clone_tasks(ST, lg):
    lid = lg["id"]
    name = lg.get("name") or lid
    ver = lg.get("ootp_version") or "27"
    cleanup = py(CLEANUP, "--league", lid, "--junk")
    return [
        task(f"sim_clones.{lid}", f"Sim {name} clones",
             f"Clones the {name} master save and auto-plays each clone in OOTP {ver}.",
             "calibration", headers([gate(input="ootp_ready"),
                                     step("winsim", f"Sim {name} clones", py(WINSIM, "--league", lid, "--runs", "{runs}"))]),
             leagues=[lid], requires=[lid], fl=flags(drives_ootp=True, long=True),
             locks=["ootp", f"clones.{lid}"], time="Depends on OOTP sim speed",
             inputs=[ootp_ready(f"OOTP {ver} is open inside a league other than the master, and nothing else needs "
                                "the mouse."), runs_input(int((lg.get("ootp_profile") or {}).get("runs") or 10))],
             finish=fin("failfast", exit_ok=0, exit_fail=1)),
        task(f"sim_clones_preview.{lid}", f"Sim {name} clones (preview)",
             f"Shows the {name} clone sim plan. Clones nothing and clicks nothing.",
             "calibration", headers([step("preview", "Show the plan",
                                          py(WINSIM, "--league", lid, "--runs", "1", "--dry-run"), "ignore")]),
             leagues=[lid], requires=[lid], fl=flags(read_only=True), time="Seconds"),
        task(f"cleanup_clones.{lid}", f"Clean up {name} clones",
             f"Deletes {name} clone saves that are archived or have no complete dumps. It lists every folder and "
             "asks first.",
             "calibration", headers([step("cleanup", "Delete the clone saves", cleanup, job=cleanup_job(cleanup))]),
             leagues=[lid], requires=[lid], locks=[f"clones.{lid}"], time="Under a minute plus your answer",
             finish=fin("failfast", exit_ok=None, exit_fail=None)),
    ]


# ---------------------------------------------------------------- tasks with no bat (4.6)

def t_ml_tasks(ST):
    """The retrain cards price DEV first, the way Bank Dev Seasons does (see
    dev_price_steps). A card that reruns the DEV odds reads the DEV dump folder
    (dev_odds sums the playing time from its per-game files), so it holds
    dumps.DEV like Bank Dev Seasons and never runs while Sim Dev League sims."""
    extras = ST.extra_leagues()
    out = []
    steps = dev_price_steps(ST, ("TGS", "BLM")) + ml_retrain_steps() + ml_extra_steps(extras)
    out.append(task("retrain_ml", "Retrain the ML dev models",
                    "Values the DEV seasons with the current TGS and BLM engines, then rebuilds the DEV age curve, "
                    "odds and dev signals. Retrains the ML dev models for TGS and BLM on every banked DEV season and "
                    "rescores TGS, BLM and the leagues that use their models. Needs about 13 GB of memory.",
                    "dev", headers(steps), leagues=["DEV", "TGS", "BLM"] + list(extras), requires=["TGS", "BLM"],
                    fl=flags(heavy=True, long=True, writes_app_data=True, needs_archive=True),
                    locks=["dumps.DEV"], time="Hours; about 13 GB of memory",
                    finish=fin("failfast", exit_ok=0, exit_fail=1)))
    for b in ("TGS", "BLM"):
        peak, path = r"tgs-viz\backtest\ml\peak.py", r"tgs-viz\backtest\ml\path.py"
        xs = [x for x, basis in extras.items() if basis == b]
        st = dev_price_steps(ST, (b,)) + [
            step("ml_dataset", f"{b} ML training rows", ml(ML_DATASET, "--basis", b, "--write")),
            step("ml_peak", f"{b} ML peak model", ml(peak, "fit-final", "--basis", b)),
            step("ml_path", f"{b} ML path model", ml(path, "fit-final", "--basis", b)),
            step("ml_check", f"{b} ML model check", ml(r"tgs-viz\backtest\ml\predict.py", "check", "--basis", b)),
            step("ml_score", f"{b} ML scores", ml(ML_SCORE, "--league", b, "--write"), app=True),
        ] + ml_extra_steps(xs)
        rescored = f"{b}" + (" and " + ", ".join(xs) if xs else "")
        if b == "BLM":
            desc = ("Values the DEV seasons with the current BLM engine, then rebuilds the DEV age curve, odds and "
                    f"the dev signals of every league. Retrains the BLM ML dev models only, then rescores {rescored}.")
            lgs = ["DEV"] + [lg for lg in ("TGS", "BLM") if lg == b or lg in ST.leagues()] + list(extras)
            locks = ["dumps.DEV"]
        else:
            desc = (f"Values the DEV seasons with the current TGS engine. Retrains the TGS ML dev models only, then "
                    f"rescores {rescored}.")
            lgs, locks = ["DEV", b] + xs, []
        out.append(task(f"retrain_ml.{b}", f"Retrain the {b} ML models", desc,
                        "dev", headers(st), leagues=lgs, requires=[b],
                        fl=flags(heavy=True, long=True, writes_app_data=True, needs_archive=True),
                        locks=locks, time="Hours; about 13 GB of memory",
                        finish=fin("failfast", exit_ok=0, exit_fail=1)))
    rescore = []
    for lg in ["TGS", "BLM"] + list(extras):
        rescore += [
            step(f"{lg.lower()}_devsignals", f"{lg} dev signals", py(DEV_SIGNALS, "--league", lg, "--write"), "collect",
                 f"{lg}-devsignals", app=True),
            step(f"{lg.lower()}_ml_rows", f"{lg} ML rows", ml(ML_DATASET, "--basis", lg, "--score-only", "--write"),
                 "collect", f"{lg}-ml-rows"),
            step(f"{lg.lower()}_ml_score", f"{lg} ML scores", ml(ML_SCORE, "--league", lg, "--write"), "collect",
                 f"{lg}-ml-score", app=True),
        ]
    out.append(task("dev_rescore", "Rescore dev signals and ML",
                    "Reruns the dev signals and ML dev scores for every league with the current models. "
                    "No retraining.",
                    "dev", headers(rescore), leagues=["TGS", "BLM"] + list(extras), requires=["TGS", "BLM"],
                    fl=flags(writes_app_data=True, needs_archive=True), time="No retraining; a few minutes"))
    return out


def player_leagues(ST):
    return [lid for lid, lg in ST.leagues().items() if lg.get("type") in ("statsplus", "local_export")]


def t_everyday_extra(ST):
    out = []
    players = player_leagues(ST)
    choices = [{"value": "all", "label": "All leagues"}] + [
        {"value": l, "label": (ST.league(l) or {}).get("name") or l} for l in players]
    out.append(task("bank_market_fit", "Bank market fit",
                    "Refits the market value model of each league from its current players. It is the only writer of "
                    "market_fit.json.",
                    "everyday", headers([step(f"market_{l.lower()}", f"{l} market fit",
                                              node(r"tgs-viz\scripts\bank_market_fit.mjs", l), "collect", f"{l}-market",
                                              app=True) for l in players]),
                    leagues=players, inputs=[inp("league", "choice", "League", "One league, or all of them.",
                                                 default="all", choices=choices)],
                    fl=flags(writes_app_data=True), time="A minute or two", expand="bank_market_fit"))
    iafa_lgs = [l for l in ST.online_leagues() if (ST.league(l) or {}).get("ootp_save")]
    if iafa_lgs:
        out.append(task("iafa_board", "Update international board",
                        "Builds the international amateur free agent board from your OOTP export and the cached pull.",
                        "everyday", headers([step("iafa", "International board",
                                                  py(r"tgs-viz\ingest\iafa.py", "--league", "{league}", "--write"),
                                                  app=True)]),
                        leagues=iafa_lgs, inputs=[inp("league", "choice", "League", "", required=True,
                                                      default=iafa_lgs[0],
                                                      choices=[{"value": l, "label": l} for l in iafa_lgs])],
                        fl=flags(writes_app_data=True), time="Under a minute"))
    if "TGS" in ST.slug_map() and "BLM" in ST.slug_map():
        out.append(task("parks_update", "Update park factors",
                        "Rebuilds the park factors for TGS and BLM from each league's home team, then rebuilds both "
                        "leagues' app data from the cached pull. Run it after you change My team.",
                        "season", headers([
                            step("parks", "Park factors", py(r"tgs-viz\ingest\parks.py", "--write"), app=True),
                            step("tgs_ratings", "TGS app data",
                                 py(REFRESH, "--statsplus", "--from-cache", "--league", "TGS", "--write"), "collect",
                                 "TGS-ratings", app=True),
                            step("blm_ratings", "BLM app data",
                                 py(REFRESH, "--statsplus", "--from-cache", "--league", "BLM", "--slug", "blm", "--write"),
                                 "collect", "BLM-ratings", app=True),
                        ]), leagues=["TGS", "BLM"], requires=["TGS", "BLM"],
                        fl=flags(network=True, writes_app_data=True, needs_archive=True), time="A few minutes"))
    out.append(task("pull_report", "Data date report",
                    "Data date report: what the app is serving. Shows, per league, the date of the data on disk.",
                    "everyday", headers([step("report", "Data date report", py(PULL_REPORT), "report")]),
                    fl=flags(read_only=True), time="Seconds",
                    finish=fin("fails", ok=[""], fails=[""], exit_ok=None, report_step="report",
                               report_verdict="lenient")))
    return out


def doctor_task():
    """The setup check. Needs no settings, so the catalog can offer it when the
    settings files are broken."""
    return task("doctor", "Setup check",
                "Checks Python, Node, the app packages, the settings, tokens, OOTP folders and each league's "
                "data. Changes nothing and needs no internet.",
                "setup", headers([step("doctor", "Setup check", py(r"tgs-viz\tools\doctor.py"), "report")]),
                fl=flags(read_only=True), time="Under a minute",
                finish=fin("fails", ok=[""], fails=[""], exit_ok=None, report_step="doctor",
                           report_verdict="lenient"))


def t_setup_tasks(ST, state):
    out = []
    online = ST.online_leagues()
    if online:
        out.append(task("token_check", "Check StatsPlus tokens",
                        "Asks StatsPlus whether each saved token still works. Needs internet.",
                        "setup", headers([step("check", "Token check", py(TOKEN, "--check"))]),
                        fl=flags(read_only=True, network=True), time="Seconds"))
        out.append(task("token_set", "Replace a StatsPlus token",
                        "Saves a new StatsPlus token for one league in StatsPlus Tokens.txt. Tokens expire after 90 days.",
                        "setup", headers([step("token", "Save the token", py(NEW_LEAGUE, "token", "--league", "{league}"),
                                               env={"TGS_NL_TOKEN": "@secret:token"})]),
                        leagues=online,
                        fl=flags(secret_inputs=True), time="Seconds",
                        inputs=[inp("league", "choice", "League", "", required=True, default=online[0],
                                    choices=[{"value": l, "label": (ST.league(l) or {}).get("name") or l,
                                              "token_line": ST.slug(l).upper() + "="} for l in online]),
                                inp("token", "secret", "StatsPlus token",
                                    "The Current Token from your league's statsplus.net Prefs page.", required=True,
                                    fmt="statsplus_token")],
                        finish=fin("failfast", exit_ok=0, exit_fail=None)))
    out.append(task("restore_ratings_db", "Rebuild ratings archive",
                    "Rebuilds the ratings archive (ratings_history.db) from the saved vintages. It refuses when an "
                    "archive already exists.",
                    "setup", headers([step("restore", "Rebuild the archive",
                                           py(r"tgs-viz\backtest\vintage_backup.py", "--restore"))]),
                    fl=flags(hidden=bool(state.get("ratings_db_exists"))), time="A few minutes"))
    out.append(doctor_task())
    if "DEV" in ST.leagues():
        dev_save = (ST.league("DEV") or {}).get("ootp_save") or "DEV TESTS"
        out.append(task("dev_test_load", "Test DEV loading",
                        "First-run check: loads the DEV save through File, Load Game and saves a screenshot. "
                        "It never sims.",
                        "dev", headers([gate(input="ootp_ready"),
                                        step("test_load", "Load test", py(WINSIM, "--league", "DEV", "--test-load", dev_save),
                                             "ignore")]),
                        leagues=["DEV"], requires=["DEV"], fl=flags(drives_ootp=True), locks=["ootp"],
                        time="Under a minute",
                        inputs=[ootp_ready("OOTP 27 is open inside a league, and nothing else needs the mouse.")]))
        out.append(task("dev_test_year", "Test the DEV year picker",
                        "First-run check: opens the date picker in the loaded DEV league and saves screenshots. "
                        "It never sims.",
                        "dev", headers([gate(input="ootp_ready"),
                                        step("test_year", "Year picker test", py(WINSIM, "--league", "DEV", "--test-year"),
                                             "ignore")]),
                        leagues=["DEV"], requires=["DEV"], fl=flags(drives_ootp=True), locks=["ootp"],
                        time="Under a minute",
                        inputs=[ootp_ready("OOTP 27 is open with DEV TESTS loaded, and nothing else needs the mouse.")]))
    out.append(task("winsim_games", "List OOTP installs",
                    "Lists the OOTP versions and saved_games folders the sim tool finds on this PC.",
                    "ootp", headers([step("games", "OOTP installs", py(WINSIM, "--games"), "ignore")]),
                    fl=flags(read_only=True), time="Seconds"))
    if "BLM" in ST.leagues():
        out.append(task("sim_blm_preview", "Sim BLM (preview)",
                        "Shows the BLM clone sim plan. Clones nothing and clicks nothing.",
                        "calibration", headers([step("preview", "Show the plan",
                                                     py(WINSIM, "--league", "BLM", "--runs", "1", "--dry-run"), "ignore")]),
                        requires=["BLM"], fl=flags(read_only=True), time="Seconds"))
    for lg in ("TGS", "BLM"):
        if lg in ST.leagues():
            cleanup = py(CLEANUP, "--league", lg, "--junk")
            out.append(task(f"cleanup_clones.{lg}", f"Clean up {lg} clones",
                            f"Deletes {lg} clone saves that are archived or have no complete dumps. It lists every "
                            "folder and asks first. Refuses while Grind or Sim runs.",
                            "calibration", headers([step("cleanup", "Delete the clone saves", cleanup,
                                                         job=cleanup_job(cleanup))]),
                            leagues=[lg], requires=[lg], locks=[f"clones.{lg}"], time="Under a minute plus your answer",
                            finish=fin("failfast", exit_ok=None, exit_fail=None)))
    return out


# ---------------------------------------------------------------- New League (12.3)

NL_FIELDS = [
    ("type", "choice", "League type"), ("id", "text", "League id"), ("name", "text", "Name"),
    ("my_org", "text", "Your org"), ("slug", "text", "StatsPlus slug"), ("basis", "text", "Calibration"),
    ("ootp_version", "text", "OOTP version"), ("ootp_save", "text", "OOTP save"),
    ("history_first_date", "text", "History start date"), ("foreign_league_ids", "text", "Foreign league ids"),
    ("dump_dir", "text", "Dump folder"), ("years", "text", "Seasons per run"),
    ("resume_after", "text", "Resume after (s)"), ("nostart_abort", "text", "No-start abort (s)"),
    ("master", "text", "Master save"), ("prefix", "text", "Clone prefix"), ("start_year", "text", "Start year"),
    ("target_year", "text", "Target year"), ("runs", "text", "Clones per run"),
]


def t_new_league():
    ins = []
    for name, typ, label in NL_FIELDS:
        if typ == "choice":
            ins.append(inp(name, "choice", label, "", required=True,
                           choices=[{"value": v, "label": v} for v in ("statsplus", "local_export", "dev", "clone")]))
        else:
            # the id builds lock names and paths before the check step runs, so refuse a bad one here (12.1)
            ins.append(inp(name, "text", label, "", required=name in ("id", "name"),
                           pattern=r"^[A-Z0-9]{2,8}$" if name == "id" else None))
    ins.append(inp("token", "secret", "StatsPlus token", "Optional. Saved on the league's line in StatsPlus Tokens.txt.",
                   fmt="statsplus_token"))
    ins += cookie_inputs(None)
    return task("new_league", "Add a league",
                "Adds a league to the app. Started by the New League wizard.",
                "leagues", [], fl=flags(hidden=True, writes_app_data=True, needs_archive=True, secret_inputs=True),
                time="Minutes", inputs=ins,
                rollback={"run": py(NEW_LEAGUE, "rollback", "--spec", "{spec}", "--precheck", "{precheck}"),
                          "until_step": "register"},
                expand="new_league", finish=fin("fails", exit_ok=None))


def new_league_steps(inputs):
    """The steps of a new_league job, from inputs.type (12.3)."""
    typ = str(inputs.get("type") or "")
    check = step("check", "Check the new league", py(NEW_LEAGUE, "check", "--spec", "{spec}", "--precheck-out", "{precheck}"))
    profile = step("profile", "Save its settings", py(NEW_LEAGUE, "profile", "--spec", "{spec}"))
    register = step("register", "Register it in the app", py(NEW_LEAGUE, "register", "--spec", "{spec}"), app=True,
                    app_leagues=["{id}", "*"])
    if typ == "statsplus":
        steps = [
            check, profile,
            step("token", "Save the StatsPlus token", py(NEW_LEAGUE, "token", "--spec", "{spec}"),
                 env={"TGS_NL_TOKEN": "@secret:token"}),
            step("ratings", "First ratings pull",
                 py(REFRESH, "--statsplus", "--league", "{id}", "--slug", "{slug}", "--calib", "{basis}", "--write"),
                 app=True, app_leagues=["{id}"], env={"STATSPLUS_COOKIE": "@cookie_given"}),
            step("draft", "Draft board", py(DRAFT, "--league", "{id}", "--slug", "{slug}", "--calib", "{basis}", "--write"),
                 "collect", "draft", app=True, app_leagues=["{id}"], env={"STATSPLUS_COOKIE": "@cookie_given"}),
            register,
            step("trends", "Rating trends", py(RATINGS_DB, "--export", "--league", "{id}"), "collect", "trends", app=True,
                 app_leagues=["{id}"]),
            step("devsignals", "Dev signals", py(DEV_SIGNALS, "--league", "{id}", "--write"), "collect", "dev-signals",
                 app=True, app_leagues=["{id}"]),
            step("ml_rows", "ML rows", ml(ML_DATASET, "--basis", "{id}", "--score-only", "--write"), "collect", "ml-rows"),
            step("ml_score", "ML scores", ml(ML_SCORE, "--league", "{id}", "--write"), "collect", "ml-score", app=True,
                 app_leagues=["{id}"]),
        ]
    elif typ == "local_export":
        steps = [
            check, profile,
            step("export", "Read the save's CSV export",
                 py(r"tgs-viz\ingest\export_league.py", "--league", "{id}", "--name", "{name}", "--save", "{ootp_save}",
                    "--game", "{ootp_version}", "--calib", "{basis}", "--write"), app=True, app_leagues=["{id}", "*"]),
            register,
            step("devsignals", "Dev signals", py(DEV_SIGNALS, "--league", "{id}", "--write"), "collect", "dev-signals",
                 app=True, app_leagues=["{id}"]),
            step("ml_rows", "ML rows", ml(ML_DATASET, "--basis", "{id}", "--score-only", "--write"), "collect", "ml-rows"),
            step("ml_score", "ML scores", ml(ML_SCORE, "--league", "{id}", "--write"), "collect", "ml-score", app=True,
                 app_leagues=["{id}"]),
        ]
    elif typ == "dev":
        dump = py(r"tgs-viz\backtest\dump_vintages.py", "--league", "{id}", "--write")
        if str(inputs.get("dump_dir") or "").strip():
            dump += ["--dump-dir", "{dump_dir}"]
        steps = [
            check, profile,
            step("dump_vintages", "Bank its yearly dumps", dump),
            step("trends", "Trends file", py(RATINGS_DB, "--export", "--league", "{id}"), "ignore", app=True,
                 app_leagues=["{id}"]),
            register,
        ]
    elif typ == "clone":
        steps = [check, profile,
                 step("preview", "Check the clone plan", py(WINSIM, "--league", "{id}", "--runs", "1", "--dry-run")),
                 register]
    else:
        steps = [check]
    return headers(steps)


def new_league_locks(typ, lid):
    if not lid:
        return []
    if typ == "dev":
        return [f"dumps.{lid}"]
    if typ == "clone":
        return [f"clones.{lid}"]
    return []


def t_new_league_cleanup():
    return task("new_league_cleanup", "Clean up unfinished league",
                "Undoes what a New League job did before it stopped: moves its new folders aside and removes its "
                "settings and app entries. Safe to run twice.",
                "leagues", headers([step("rollback", "Undo the unfinished league",
                                         py(NEW_LEAGUE, "rollback", "--spec", r"{control}\jobs\{job_id}\new_league_spec.json",
                                            "--precheck", r"{control}\jobs\{job_id}\precheck.json"),
                                         app=True, app_leagues=["*"])]),
                fl=flags(hidden=True, writes_app_data=True, needs_archive=True), time="Seconds",
                inputs=[inp("job_id", "text", "Job id", "The id of the New League job to undo.", required=True,
                            pattern=JOB_ID_PATTERN)],
                expand="new_league_cleanup", finish=fin("failfast", exit_ok=0, exit_fail=None))


def t_remove_league(ST, lg):
    lid = lg["id"]
    name = lg.get("name") or lid
    typ = lg.get("type")
    return task(f"remove_league.{lid}", f"Remove {name} from the app",
                f"Moves the {name} app data aside (into the .control folder) and removes its settings and league "
                "list entries. Its ratings archive, vintages and token line stay.",
                "leagues", headers([step("remove", "Remove the league", py(NEW_LEAGUE, "remove", "--league", lid),
                                         app=True)]),
                leagues=[lid], requires=[lid], fl=flags(writes_app_data=True, needs_archive=True),
                locks=new_league_locks(typ, lid), time="Seconds",
                inputs=[inp("confirm_id", "text", f"Type {lid} to confirm", "", required=True, equals=lid)],
                finish=fin("failfast", exit_ok=0, exit_fail=None))


# ---------------------------------------------------------------- self tests (4.9)

def st_step(id, *args, **kw):
    return step(id, kw.pop("title", f"Self test step {id}"), py(SELFTEST_SCRIPT, *args), kw.pop("on_error", "fail"),
                **kw)


def t_selftests():
    def mk(id, title, steps, **kw):
        kw.setdefault("time", "Seconds")
        kw.setdefault("fl", flags())
        return task(id, title, kw.pop("description", "A harmless test of the Control panel."), "selftest",
                    headers(steps), **kw)

    out = [
        mk("selftest.ok", "Self test ok", [st_step("s1", "ok")]),
        mk("selftest.fail_collect", "Self test fail collect", [
            st_step("s1", "print", "step one", on_error="collect", tag="T1"),
            st_step("s2", "exit", "1", on_error="collect", tag="T2"),
            st_step("s3", "print", "step three", on_error="collect", tag="T3")]),
        mk("selftest.fail_fast", "Self test fail fast", [
            st_step("s1", "print", "step one"), st_step("s2", "exit", "1"), st_step("s3", "print", "step three")],
           finish=fin("failfast", exit_ok=0, exit_fail=1)),
        mk("selftest.confirm", "Self test confirm", [
            st_step("s1", "apply", job=preview_confirm(py(SELFTEST_SCRIPT, "preview", "3"), py(SELFTEST_SCRIPT, "apply"),
                                                       SYNC_COUNT, "Apply the self test changes?"))]),
        mk("selftest.confirm_zero", "Self test confirm zero", [
            st_step("s1", "apply", job=preview_confirm(py(SELFTEST_SCRIPT, "preview", "0"), py(SELFTEST_SCRIPT, "apply"),
                                                       SYNC_COUNT, "Apply the self test changes?"))]),
        mk("selftest.gate", "Self test gate", [
            st_step("s1", "print", "before the gate"),
            gate("g1", text="Self test gate. Press Continue to run the last step, or Stop.",
                 echo=["", {"console": "  Self test gate: press a key to go on.",
                            "job": "  Self test gate: press Continue on the page to go on."}]),
            st_step("s2", "print", "after the gate")]),
        mk("selftest.long", "Self test long", [st_step(f"s{i}", "sleep", "20") for i in range(1, 7)],
           time="Two minutes", finish=fin("failfast", exit_ok=0, exit_fail=1)),
        mk("selftest.loop", "Self test loop", [st_step("s1", "sleep", "5"), st_step("s2", "sleep", "5")],
           fl=flags(endless=True), loop={"from_step": "s1", "cycle_echo": ["", " --- self test cycle {cycle} ---"]},
           time="Runs until you stop it"),
        mk("selftest.secret", "Self test secret", [
            st_step("s1", "secret", env={"TEST_SECRET": "@secret:token"})],
           fl=flags(secret_inputs=True),
           inputs=[inp("token", "secret", "Test secret", "Any text of 8 or more characters.", required=True)]),
        mk("selftest.touch", "Self test touch", [st_step("s1", "touch", "{file}", app=True)],
           fl=flags(writes_app_data=True),
           inputs=[inp("file", "text", "Data file", "A file under public/data to rewrite with the same bytes.",
                       default="TGS/r5.json")]),
        mk("selftest.corrupt", "Self test corrupt", [st_step("s1", "corrupt", "RG/iafa.json", app=True)],
           fl=flags(writes_app_data=True)),
        mk("selftest.stdin", "Self test stdin", [st_step("s1", "stdin")]),
        mk("selftest.phase", "Self test phase", [st_step("s1", "sleep", "8", data=False), st_step("s2", "sleep", "3")],
           fl=flags(endless=True), locks=["ootp"],
           loop={"from_step": "s1", "cycle_echo": ["", " --- self test cycle {cycle} ---"]},
           time="Runs until you stop it", finish=fin("failfast", exit_ok=0, exit_fail=1)),
        mk("selftest.excel", "Self test excel", [
            st_step("s0", "mkdir", "{folder}"),
            excel_check("xl", "{folder}", files=["a.xlsx"]),
            st_step("s1", "sleep", "1")],
           inputs=[inp("folder", "text", "Folder", "The folder to check for Excel lock files.",
                       default="{job_dir}\\xl")]),
        mk("selftest.hands_off", "Self test hands off", [st_step("s1", "sleep", "1", drives_ootp=True)],
           fl=flags(drives_ootp=True)),
        mk("selftest.archive", "Self test archive", [st_step("s1", "sleep", "0")], fl=flags(needs_archive=True)),
        mk("selftest.rollback", "Self test rollback", [
            st_step("s1", "sleep", "1"), st_step("s2", "sleep", "20"), st_step("s3", "sleep", "0")],
           rollback={"run": py(SELFTEST_SCRIPT, "mark", "{job_dir}\\rolled_back"), "until_step": "s3"},
           finish=fin("failfast", exit_ok=0, exit_fail=1)),
        mk("selftest.leagues", "Self test leagues", [
            st_step("s1", "sleep", "1", app=True, app_leagues=["TGS"]),
            st_step("s2", "sleep", "1", app=True, app_leagues=["TGS"]),
            st_step("s3", "sleep", "1", app=True, app_leagues=["BLM"]),
            st_step("s4", "sleep", "1", app=True, app_leagues=[])],
           fl=flags(writes_app_data=True)),
    ]
    return out


# ---------------------------------------------------------------- registry

def defaults_league_ids(ST):
    try:
        return set((ST.defaults_raw().get("leagues") or {}).keys())
    except Exception:
        return set()


def all_tasks(ST, state=None):
    """Every task, including those whose leagues are off. Each has
    requires_leagues; available() says whether it may run."""
    state = dict(state or {})
    out = [t_get_ratings()]
    h = t_get_history(ST)
    if h:
        out.append(h)
    out += [t_bank_season(), t_bank_dev(ST), t_grind(ST, "TGS"), t_grind(ST, "BLM"), t_recalibrate_tgs(),
            t_recalibrate_blm(), t_sim_dev(), t_sync_metadata(), t_dispersal(ST), t_draft_board()]
    out += t_ootp_tools()
    defaults_ids = defaults_league_ids(ST)
    for lid, lg in ST.leagues(include_disabled=True).items():
        typ = lg.get("type")
        if typ == "statsplus":
            out.append(t_update_statsplus(ST, lg))
            if lid not in defaults_ids:
                out.append(t_draft_league(ST, lg))
                out.append(t_bank_season_league(ST, lg))
        elif typ == "local_export":
            out.append(t_update_local(ST, lg))
        elif typ == "dev":
            out.append(t_update_dev(ST, lg))
            if lid != "DEV":
                out.append(t_sim_dev_other(ST, lg))
        elif typ == "clone":
            out += t_clone_tasks(ST, lg)
        if lid not in defaults_ids:
            out.append(t_remove_league(ST, lg))
    out += t_ml_tasks(ST)
    out += t_everyday_extra(ST)
    out += t_setup_tasks(ST, state)
    out += [t_new_league(), t_new_league_cleanup()]
    if state.get("selftest"):
        out += t_selftests()
    trends = list(ST.slug_map())
    for t in out:
        finalize(t, trends)
    return out


def available(t, ST):
    """None when every required league is enabled and not pending, else a plain reason."""
    active = ST.leagues()
    for lid in t.get("requires_leagues") or []:
        if lid not in active:
            lg = ST.league(lid)
            if lg is None:
                return f"This task needs the league {lid}, which is not in the settings."
            if lg.get("pending"):
                return f"This task needs the league {lid}, which is still being added."
            return f"This task needs the league {lid}, which is turned off in the settings."
    return None


def build_registry(settings_module, state=None):
    """The task list for the catalog: tasks whose leagues are all enabled."""
    ST = settings_module
    return [t for t in all_tasks(ST, state) if available(t, ST) is None]


def find(tasks, task_id):
    for t in tasks:
        if t["id"] == task_id:
            return t
    return None


def expand(t, inputs, ST):
    """A copy of the task with its run-time steps for tasks whose steps depend on
    inputs (new_league, bank_market_fit, new_league_cleanup)."""
    t = copy.deepcopy(t)
    kind = t.get("expand")
    trends = list(ST.slug_map())
    if kind == "new_league":
        t["steps"] = new_league_steps(inputs)
        t["locks"] = new_league_locks(str(inputs.get("type") or ""), str(inputs.get("id") or ""))
    elif kind == "bank_market_fit":
        want = str(inputs.get("league") or "all")
        if want != "all":
            t["steps"] = [s for s in t["steps"] if s["id"] == f"market_{want.lower()}"]
    elif kind == "new_league_cleanup":
        import joblock
        jid = str(inputs.get("job_id") or "")
        spec = joblock.read_json(os.path.join(joblock.job_dir(jid), "new_league_spec.json")) if jid else None
        if isinstance(spec, dict):
            t["locks"] = new_league_locks(str(spec.get("type") or ""), str(spec.get("id") or ""))
    finalize(t, trends)
    return t
