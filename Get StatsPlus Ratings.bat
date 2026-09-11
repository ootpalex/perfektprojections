@echo off
setlocal
cd /d "%~dp0"
echo.
echo  ===============================================
echo    Pull player ratings from StatsPlus  (TGS + BLM)
echo  ===============================================
echo.
echo  You need two values from your browser while logged in to
echo  statsplus.net:  sessionid  and  csrftoken
echo    F12  -^>  Application (or Storage)  -^>  Cookies  -^>  statsplus.net
echo  (StatsPlus logins are per-league: this run updates the league your
echo   browser is signed into right now. The other league keeps its last
echo   data - open its statsplus.net page and run this again to update it.
echo   The report at the end shows exactly what the app is serving.)
echo.
set /p SID=Paste your sessionid value, then press Enter:
set /p CSRF=Paste your csrftoken value, then press Enter:
set "STATSPLUS_COOKIE=sessionid=%SID%;csrftoken=%CSRF%"
set "FAILS="
echo.
echo  Working... pulling TGS, then BLM. StatsPlus builds each export on its
echo  end, so this can take a couple of minutes. Leave this window open.
echo.
echo  --- TGS (OSA ratings) ---
python "tgs-viz\ingest\refresh.py" --statsplus --league TGS --write
if errorlevel 1 set "FAILS=%FAILS% TGS-ratings"
echo.
echo  --- TGS draft board (from your OOTP draft-pool CSV + the pull) ---
echo  (Export the pool from OOTP's Amateur Draft screen to import_export first.
echo   Skips automatically if the CSV isn't there.)
python "tgs-viz\ingest\draft.py" --league TGS --write
if errorlevel 1 set "FAILS=%FAILS% TGS-draft"
echo.
echo  --- TGS Rule 5 pool (from your OOTP R5 draft-pool export + the pull) ---
echo  (Skips automatically if the CSV isn't there.)
python "tgs-viz\ingest\r5.py" --league TGS --write
if errorlevel 1 set "FAILS=%FAILS% TGS-r5"
echo.
echo  --- BLM (scouted ratings) ---
python "tgs-viz\ingest\refresh.py" --statsplus --league BLM --slug blm --write
if errorlevel 1 set "FAILS=%FAILS% BLM-ratings"
echo.
echo  --- BLM draft board (pool CSV if present, else the draft_eligible API; live picks applied) ---
python "tgs-viz\ingest\draft.py" --league BLM --slug blm --write
if errorlevel 1 set "FAILS=%FAILS% BLM-draft"
echo.
echo  --- BLM Rule 5 pool (from your OOTP R5 draft-pool export + the pull) ---
echo  (Skips automatically if the CSV isn't there.)
python "tgs-viz\ingest\r5.py" --league BLM --write
if errorlevel 1 set "FAILS=%FAILS% BLM-r5"
echo.
echo  --- Age curves (measured dev rates; auto-skips short/contaminated archives) ---
python "tgs-viz\engine\agecurve_fit.py" --league TGS --write
if errorlevel 1 set "FAILS=%FAILS% TGS-agecurve"
python "tgs-viz\engine\agecurve_fit.py" --league BLM --write
if errorlevel 1 set "FAILS=%FAILS% BLM-agecurve"
echo.
echo  --- Rating trends (app history panel) ---
python "tgs-viz\backtest\ratings_db.py" --export
if errorlevel 1 set "FAILS=%FAILS% rating-trends"
echo.
if defined FAILS (
  echo   Steps that did not update:%FAILS%
  echo   ^(each one said why above - a league you are not signed into is normal^)
)
rem The report below trusts only the files on disk - it shows, per league,
rem the date of the data the app is ACTUALLY serving right now.
python "tgs-viz\ingest\pull_report.py"
echo.
pause
endlocal
