@echo off
setlocal
cd /d "%~dp0.."
echo.
echo  ===============================================
echo    Pull player ratings from StatsPlus  (TGS + BLM)
echo  ===============================================
echo.
echo  With a StatsPlus token saved for each league (StatsPlus Tokens.txt),
echo  this updates TGS and BLM in one run and asks for nothing. A token lasts
echo  90 days. Then paste the new one into StatsPlus Tokens.txt.
echo.
echo  A league with no saved token needs your browser login instead: two values
echo  from your browser while logged in to statsplus.net:  sessionid  and  csrftoken
echo    F12  -^>  Application (or Storage)  -^>  Cookies  -^>  statsplus.net
echo  (A browser login is per-league: it updates only the league your browser
echo   is signed into right now. The other league keeps its last data.
echo   The report at the end shows exactly what the app is serving.)
echo.
set "FAILS="
set "TOK_TGS="
set "TOK_BLM="
rem --have exits 0 when the league has a saved token. It warns when a token
rem is near its 90-day end and never shows the token.
python "tgs-viz\ingest\statsplus_token.py" --have TGS
if not errorlevel 1 set "TOK_TGS=1"
python "tgs-viz\ingest\statsplus_token.py" --have BLM
if not errorlevel 1 set "TOK_BLM=1"
if defined TOK_TGS if defined TOK_BLM goto :both_tokens
if defined TOK_TGS goto :one_token
if defined TOK_BLM goto :one_token
rem No token saved: ask for the browser cookies, as before.
echo  Tip: Paste a token for each league into StatsPlus Tokens.txt. After that,
echo  this bat asks for no cookies and updates both leagues in one run.
echo.
set /p SID=Paste your sessionid value, then press Enter:
set /p CSRF=Paste your csrftoken value, then press Enter:
set "STATSPLUS_COOKIE=sessionid=%SID%;csrftoken=%CSRF%"
goto :pull

:both_tokens
echo  StatsPlus tokens are saved for TGS and BLM: no browser cookies needed.
set "STATSPLUS_COOKIE="
goto :pull

:one_token
set "HAVE=BLM"
set "NOTOK=TGS"
set "NOSLUG=tgs"
if defined TOK_TGS set "HAVE=TGS"
if defined TOK_TGS set "NOTOK=BLM"
if defined TOK_TGS set "NOSLUG=blm"
echo  A StatsPlus token is saved for %HAVE%, but not for %NOTOK%.
echo  Paste the %NOTOK% token into StatsPlus Tokens.txt. Then this bat asks for nothing.
echo  To update %NOTOK% in this run anyway, open statsplus.net/%NOSLUG% in your browser
echo  (logged in) and paste its cookies below. Press Enter to skip %NOTOK% this run.
echo.
set "SID="
set "CSRF="
set "STATSPLUS_COOKIE="
set /p SID=Paste your sessionid value (Enter = skip %NOTOK%): 
if not defined SID goto :pull
set /p CSRF=Paste your csrftoken value, then press Enter: 
set "STATSPLUS_COOKIE=sessionid=%SID%;csrftoken=%CSRF%"

:pull
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
echo  --- Dev signals (DEV-league odds of becoming a regular, per 16-22 year old) ---
python "tgs-viz\backtest\dev_signals.py" --league TGS --write
if errorlevel 1 set "FAILS=%FAILS% TGS-devsignals"
python "tgs-viz\backtest\dev_signals.py" --league BLM --write
if errorlevel 1 set "FAILS=%FAILS% BLM-devsignals"
echo.
echo  --- ML dev scores (one model set per league, on the new pulls; no retraining) ---
rem Must run after the dev signals lines: the app uses the ML only when both
rem files come from the same pull, and falls back to the old numbers if not.
py -3.14 "tgs-viz\backtest\ml\dataset.py" --basis TGS --score-only --write
if errorlevel 1 set "FAILS=%FAILS% TGS-ml-rows"
py -3.14 "tgs-viz\backtest\ml\dataset.py" --basis BLM --score-only --write
if errorlevel 1 set "FAILS=%FAILS% BLM-ml-rows"
py -3.14 "tgs-viz\backtest\ml\score.py" --league TGS --write
if errorlevel 1 set "FAILS=%FAILS% TGS-ml-score"
py -3.14 "tgs-viz\backtest\ml\score.py" --league BLM --write
if errorlevel 1 set "FAILS=%FAILS% BLM-ml-score"
echo.
if defined FAILS (
  echo   Steps that did not update:%FAILS%
  echo   ^(each one said why above - a league with no token and no login this run is normal^)
)
rem The report below trusts only the files on disk - it shows, per league,
rem the date of the data the app is ACTUALLY serving right now.
python "tgs-viz\ingest\pull_report.py"
echo.
pause
endlocal
