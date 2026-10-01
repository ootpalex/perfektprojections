@echo off
title DEV TESTS - sim seasons + bank the dumps (OOTP 27)
cd /d "%~dp0.."

set "YEARS=%~1"
if "%YEARS%"=="" set "YEARS=5"

echo ============================================================
echo   SIM DEV LEAGUE  -  %YEARS% seasons of "DEV TESTS"  -^>  ratings archive
echo ------------------------------------------------------------
echo   DEV TESTS is a plain OOTP 27 league, every team AI-controlled,
echo   simmed in place year after year. Its yearly CSV dump gives
echo   true ratings and personalities: no scouting, no StatsPlus.
echo   Each run: load DEV TESTS, auto-play %YEARS% seasons, wait for the
echo   last dump, bank the dumps as ratings vintages, rebuild the DEV
echo   trends file for the web app. Run it again any time: it starts
echo   from the last dump on disk. Dumps are never deleted or moved.
echo.
echo   START STATE: OOTP 27 open and INSIDE a league. Any league is
echo   fine, DEV TESTS itself too (save it first: the tool reloads
echo   it from disk). The main menu alone is NOT enough: the tool
echo   drives FILE -^> Load Game. Not running as administrator.
echo   In DEV TESTS, "Export CSV files after each simulated season"
echo   must be ON in the game settings, or nothing gets banked.
echo.
echo   FIRST TIME ONLY, before this bat, check the Load Game row and
echo   the date picker on the real league (neither one sims):
echo     python ootp\winsim.py --league DEV --test-load "DEV TESTS"
echo     python ootp\winsim.py --league DEV --test-year
echo   then look at ootp\_diag_loaded.png and _diag_after_setyear.png.
echo.
echo   Hands off the mouse and keyboard once it starts.
echo   ABORT: slam the mouse into a screen corner, or Ctrl+C.
echo   Ctrl+C stops this window, not the sim already running in OOTP.
echo   Another count: "Sim Dev League.bat 3" sims 3 seasons.
echo ============================================================
echo.
pause

echo.
echo  --- 1. sim %YEARS% season(s) ---
python "ootp\winsim.py" --league DEV --sim --years %YEARS%
if errorlevel 1 goto :fail

echo.
echo  --- 2. bank the yearly dumps as ratings vintages ---
if not exist "tgs-viz\backtest\dump_vintages.py" (
  echo   tgs-viz\backtest\dump_vintages.py is missing. The seasons are simmed and on disk; nothing was banked.
  goto :fail
)
python "tgs-viz\backtest\dump_vintages.py" --league DEV --write
if errorlevel 1 goto :fail

echo.
echo  --- 3. rebuild the DEV trends file for the web app ---
python "tgs-viz\backtest\ratings_db.py" --export --league DEV
if errorlevel 1 goto :fail

echo.
echo  --- 4. register DEV in the web app's league list ---
python "tgs-viz\extract_data.py" --manifest-only
if errorlevel 1 goto :fail

rem agecurve_fit.py (tgs-viz\engine) is NOT run for DEV. It prices every vintage
rem through the projection engine, which needs calib\DEV\constants-latest.json
rem and the sheet-fed constants; DEV has no engine calibration. The measured
rem growth per age for DEV comes from ratings_db.py --export (age_curves).

echo.
echo ============================================================
echo   Done. Reload the web app and pick the DEV league.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   Something failed above. Seasons already simmed stay on disk
echo   in the league's dump folder; the next run starts from the
echo   last dump. Fix the message above and rerun.
echo ============================================================
pause
exit /b 1
