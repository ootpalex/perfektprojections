@echo off
setlocal
cd /d "%~dp0.."
echo.
echo  ===============================================
echo    Update Regular Game  (OOTP 27 save, BLM settings)
echo  ===============================================
echo.
echo  BEFORE running this: open Regular Game in OOTP and export the database
echo  to CSV again (the same export as the first time). It goes to
echo    saved_games\Regular Game.lg\import_export\csv
echo  Optional: for signing demands on the international board, also export
echo  OOTP's International Amateur Free Agents screen to its import_export folder.
echo.
echo  What this does: prices every player with BLM's engine settings, builds
echo  the draft board (this year's draft class) and the international list,
echo  saves this export as a snapshot (so growth and rating trends build up as
echo  you sim), then the dev signals and the ML dev chances (the BLM-trained
echo  model). Running it again on the same export replaces that snapshot.
echo.
set "FAILS="
echo  --- Players, draft board, internationals, snapshot, rating trends ---
python "tgs-viz\ingest\export_league.py" --league RG --name "Regular Game" --save "Regular Game" --write
if errorlevel 1 set "FAILS=%FAILS% players"
echo.
echo  --- Dev signals ---
python "tgs-viz\backtest\dev_signals.py" --league RG --write
if errorlevel 1 set "FAILS=%FAILS% dev-signals"
echo.
echo  --- ML dev chances (MLB / Starter / Star %%) ---
rem Must run after the dev signals line: the app uses the ML only when both
rem files come from the same snapshot.
py -3.14 "tgs-viz\backtest\ml\dataset.py" --basis RG --score-only --write
if errorlevel 1 set "FAILS=%FAILS% ml-rows"
py -3.14 "tgs-viz\backtest\ml\score.py" --league RG --write
if errorlevel 1 set "FAILS=%FAILS% ml-score"
echo.
if defined FAILS (
  echo   Steps that did not finish:%FAILS%
  echo   ^(each one said why above^)
) else (
  echo   Done. Refresh the app ^(F5^) and pick "Regular Game" in the league menu.
)
echo.
pause
endlocal
