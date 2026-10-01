@echo off
setlocal
cd /d "%~dp0.."
echo.
echo  ===============================================
echo    Pull PAST ratings from StatsPlus  (one league)
echo  ===============================================
echo.
echo  What this does: StatsPlus can now give the ratings as they were on a
echo  past game date. This asks for one snapshot every 6 game months
echo  (Jan 1 and Jul 1 of each game year, back to where the league's history
echo  starts) and stores each one in the ratings archive under its game date
echo  (the date inside the league, not today's real date). It never changes
echo  the app's current player values: those still come from your latest
echo  normal pull. It adds history for the rating trends, the dev signals
echo  and the ML dev scores.
echo.
echo  How long: about 15 snapshots per league. StatsPlus allows one ratings
echo  request per 5 minutes, so each snapshot takes about 5 minutes. Then the
echo  archive steps below rerun; the first time, the age curve and trends
echo  steps price every new snapshot once (about 40 seconds each). Plan on
echo  about 2 hours. Leave this window open.
echo  A second run asks StatsPlus for almost nothing: dates already stored,
echo  and dates StatsPlus had no snapshot for last time, are skipped. It runs
echo  one 5-minute check job only when no token is saved for the league, or
echo  when the league has played on since your last Get StatsPlus Ratings run.
echo  Each snapshot is checked before it is stored: if StatsPlus sends today's
echo  ratings for a past date, or repeats a date, nothing from it is stored.
echo.
echo  Login: the saved StatsPlus token of the league (StatsPlus Tokens.txt
echo  saves one per league). With no saved token, this asks for your browser
echo  cookies instead, and a browser login works for ONE league: the league
echo  your browser is signed into right now.
echo.
:askleague
set "LG="
set /p LG=Which league? Type TGS or BLM, then press Enter:
if /i "%LG%"=="TGS" (set "LG=TGS" & set "SLUG=tgs" & goto haveleague)
if /i "%LG%"=="BLM" (set "LG=BLM" & set "SLUG=blm" & goto haveleague)
echo  Please type TGS or BLM.
goto askleague
:haveleague
set "USETOKEN="
rem --have exits 0 when the league has a saved token. It warns when a token
rem is near its 90-day end and never shows the token.
python "tgs-viz\ingest\statsplus_token.py" --have %LG%
if not errorlevel 1 set "USETOKEN=1"
if not defined USETOKEN goto askcookie
echo.
echo  Using your saved %LG% StatsPlus token. No browser cookies needed.
goto run
:askcookie
echo.
echo  No StatsPlus token is saved for %LG%. A token in StatsPlus Tokens.txt
echo  and removes this step. For now your browser login works: your browser
echo  must be signed into %LG% on statsplus.net.
echo  You need two values from your browser while logged in to
echo  statsplus.net:  sessionid  and  csrftoken
echo    F12  -^>  Application (or Storage)  -^>  Cookies  -^>  statsplus.net
echo.
set /p SID=Paste your sessionid value, then press Enter:
set /p CSRF=Paste your csrftoken value, then press Enter:
set "STATSPLUS_COOKIE=sessionid=%SID%;csrftoken=%CSRF%"
:run
set "FAILS="
echo.
echo  --- %LG%: past rating snapshots from StatsPlus ---
python "tgs-viz\ingest\statsplus_history.py" --league %LG% --slug %SLUG% --write
set "HX=%errorlevel%"
rem The cookie is only needed for the step above.
set "STATSPLUS_COOKIE="
set "SID="
set "CSRF="
rem Exit codes 2, 3, 6, 7, 8, 9 and 10 stop the run: the archive steps below are skipped.
if "%HX%"=="2" goto stop2
if "%HX%"=="3" goto stop3
if "%HX%"=="6" goto stop6
if "%HX%"=="7" goto stop7
if "%HX%"=="8" goto stop8
if "%HX%"=="9" goto stop9
if "%HX%"=="10" goto stop10
if not "%HX%"=="0" set "FAILS=%FAILS% %LG%-history"
echo.
echo  --- %LG% age curves (prices each new snapshot once, then reuses it) ---
python "tgs-viz\engine\agecurve_fit.py" --league %LG% --write
if errorlevel 1 set "FAILS=%FAILS% %LG%-agecurve"
echo.
echo  --- Rating trends (app history panel) ---
python "tgs-viz\backtest\ratings_db.py" --export
if errorlevel 1 set "FAILS=%FAILS% rating-trends"
echo.
echo  --- %LG% dev signals (odds of becoming a regular, per 16-22 year old) ---
python "tgs-viz\backtest\dev_signals.py" --league %LG% --write
if errorlevel 1 set "FAILS=%FAILS% %LG%-devsignals"
echo.
echo  --- %LG% ML dev scores (scoring rows, then the score; no retraining) ---
rem Must run after the dev signals line: the app uses the ML only when both
rem files come from the same pull, and falls back to the old numbers if not.
py -3.14 "tgs-viz\backtest\ml\dataset.py" --basis %LG% --score-only --write
if errorlevel 1 set "FAILS=%FAILS% %LG%-ml-rows"
py -3.14 "tgs-viz\backtest\ml\score.py" --league %LG% --write
if errorlevel 1 set "FAILS=%FAILS% %LG%-ml-score"
echo.
if defined FAILS (
  echo   Steps that did not finish:%FAILS%
  echo   ^(each one said why above^)
)
goto done

:stop2
echo.
echo   STOPPED ^(code 2^): no StatsPlus login. No token is saved for %LG% and
echo   no browser cookies were given. Nothing was fetched or stored. Run
echo   StatsPlus Tokens.txt, or run this again and paste sessionid and csrftoken.
goto skipped
:stop3
echo.
if defined USETOKEN goto stop3token
echo   STOPPED ^(code 3^): your browser is not signed into %LG% on StatsPlus
echo   ^(a login only pulls the league it is signed into^).
echo   Open statsplus.net/%SLUG% in your browser, sign in, then run this again.
echo   A token in StatsPlus Tokens.txt removes this step.
goto skipped
:stop3token
echo   STOPPED ^(code 3^): StatsPlus refused your saved %LG% token. The message
echo   above says why ^(expired, unknown, or a login is needed^). Copy the
echo   Current Token from statsplus.net/%SLUG% Prefs, run Set StatsPlus
echo   Tokens.bat, then run this again.
goto skipped
:stop6
echo.
echo   STOPPED ^(code 6^): the ratings StatsPlus sent do not look like %LG%
echo   ^(the player IDs and names do not match your %LG% pulls^). Nothing from
echo   that date was stored. Check that you typed the right league, then run again.
goto skipped
:stop7
echo.
echo   STOPPED ^(code 7^): StatsPlus sent TODAY's ratings for 3 past game dates
echo   in a row and no past date came back this run, so it ignores the date
echo   right now. Nothing from those dates was stored. Do not run this again
echo   until StatsPlus past snapshots work.
goto skipped
:stop8
echo.
echo   STOPPED ^(code 8^): StatsPlus pointed the job at another web site. Your
echo   login was NOT sent there and nothing from that job was stored. Do not
echo   run this again until the cause is found.
goto skipped
:stop9
echo.
echo   STOPPED ^(code 9^): StatsPlus says past date ratings are NOT ENABLED
echo   for %LG%. Your login worked. Nothing was stored. The league's StatsPlus
echo   owner has to switch the feature on first; then run this again.
goto skipped
:stop10
echo.
echo   STOPPED ^(code 10^): the check job for today's ratings failed, and not
echo   because of the login. The message above says why ^(no ratings,
echo   StatsPlus not reachable, or too slow^). Nothing was stored. Run
echo   Get StatsPlus Ratings.bat first, then run this again.
goto skipped
:skipped
echo   Dates stored before the stop, if any, passed every check and stay stored
echo   ^(the report above lists them^).
echo   The archive steps ^(age curves, rating trends, dev signals, ML scores^)
echo   were skipped this time.
:done
echo.
pause
endlocal
