@echo off
title DEV TESTS - bank the seasons already simmed (no simming)
cd /d "%~dp0.."

echo ============================================================
echo   BANK DEV SEASONS  -  no simming
echo ------------------------------------------------------------
echo   For when you sim DEV TESTS by hand inside OOTP. OOTP writes
echo   the yearly CSV dump by itself at every new year. This bat
echo   only picks up the dumps that are not banked yet, stores them
echo   as ratings vintages, rebuilds the DEV trends file and makes
echo   sure DEV is in the web app's league list. Then it retrains
echo   the ML dev models on every banked season and rescores TGS
echo   and BLM (step 4b is LONG: about an hour per 150 banked
echo   seasons on this PC; let it finish).
echo   Safe to run any time; already-banked years are skipped.
echo ============================================================
echo.

echo  --- 1. bank new yearly dumps ---
python "tgs-viz\backtest\dump_vintages.py" --league DEV --write
if errorlevel 1 goto :fail

echo.
echo  --- 2. rebuild the DEV trends file ---
python "tgs-viz\backtest\ratings_db.py" --export --league DEV
if errorlevel 1 goto :fail

echo.
echo  --- 2b. value the new DEV seasons with each league's engine (only new seasons) ---
rem BLM engine: also refits the measured age curve the app shows. It must run
rem before step 3, which reads these values. TGS engine: kept apart in
rem tgs-viz\backtest\.dev_cache\ml\waa_TGS for the TGS model.
python "tgs-viz\engine\agecurve_fit.py" --league DEV --calib BLM --no-guard --write
if errorlevel 1 goto :fail
python "tgs-viz\backtest\ml\reprice.py" --calib TGS
if errorlevel 1 goto :fail

echo.
echo  --- 3. rebuild the DEV odds grid (regular odds by age, Pot and growth) ---
python "tgs-viz\backtest\dev_odds.py" --write
if errorlevel 1 goto :fail

echo.
echo  --- 3b. rebuild the Make-it odds tables (odds by age and one rating band) ---
python "tgs-viz\backtest\dev_rating_odds.py" --write
if errorlevel 1 goto :fail

echo.
echo  --- 4. dev signals for TGS and BLM (the grid applied to each 16-22 year old) ---
python "tgs-viz\backtest\dev_signals.py" --league TGS --write
if errorlevel 1 goto :fail
python "tgs-viz\backtest\dev_signals.py" --league BLM --write
if errorlevel 1 goto :fail

echo.
echo  --- 4b. retrain the ML dev models, one set per league (LONG, let it finish) ---
rem Needs Python 3.14 (py -3.14). A stop in the middle of a fit leaves that
rem league with a mix of old and new models: rerun the bat to finish.
py -3.14 "tgs-viz\backtest\ml\dataset.py" --basis TGS --write
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\dataset.py" --basis BLM --write
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\peak.py" fit-final --basis TGS
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\path.py" fit-final --basis TGS
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\peak.py" fit-final --basis BLM
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\path.py" fit-final --basis BLM
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\predict.py" check --basis TGS
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\predict.py" check --basis BLM
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\score.py" --league TGS --write
if errorlevel 1 goto :fail
py -3.14 "tgs-viz\backtest\ml\score.py" --league BLM --write
if errorlevel 1 goto :fail

echo.
echo  --- 5. register DEV in the web app's league list ---
python "tgs-viz\extract_data.py" --manifest-only
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   Done. Reload the web app and pick the DEV league.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   Something failed above. Nothing is lost: the dumps stay in
echo   the league's dump folder. Fix the message and rerun.
echo ============================================================
pause
exit /b 1
