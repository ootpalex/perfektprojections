@echo off
title TGS GRIND - sim + recalibrate on repeat (close this window to stop)
cd /d "%~dp0"

echo ============================================================
echo   TGS GRIND  -  fully automatic, runs until YOU stop it
echo ------------------------------------------------------------
echo   Each cycle: 10 clones x 10 seasons (~100 seasons), then it
echo   AUTOMATICALLY recalibrates (constants -^> sheets -^> webapp),
echo   refreshes every fitted layer, archives the season data and
echo   deletes the spent clone saves. Then it starts the next
echo   cycle. No prompts, no manual steps, no leftovers.
echo.
echo   START STATE: OOTP 26 open INSIDE any league EXCEPT the
echo   Baseline master. Then hands off the mouse/keyboard.
echo.
echo   STOP: close this window (or Ctrl+C). Every finished cycle
echo   is already banked, so stopping never loses banked seasons
echo   (at worst the current in-progress clone is discarded).
echo ============================================================
echo.
pause

set CYCLE=0

:loop
set /a CYCLE+=1
echo.
echo ################  CYCLE %CYCLE%  -  simming 10 clones (~100 seasons)  ################
python "ootp\winsim.py" --league TGS --runs 10
if errorlevel 1 (
    echo   winsim reported a problem - recalibrating what finished, then stopping.
    set STOPAFTER=1
)

echo.
echo ################  CYCLE %CYCLE%  -  recalibrating  ################
python "tgs-viz\engine\calibrate.py" --csv-dir "tgs-viz\engine\calib\TGS" --dumps "C:/OOTP 26/data/saved_games/*tgs*.lg" --ratings-dir "tgs-viz\engine\calib\TGS" --json "tgs-viz\engine\calib\TGS\constants-latest.json" --archive-dir "tgs-viz\engine\calib\TGS"
if errorlevel 1 goto :fail

python "tgs-viz\ingest\sync_datapoints.py" --league TGS --calib "tgs-viz\engine\calib\TGS\constants-latest.json" --write --yes
if errorlevel 1 goto :fail

rem fitted layers + snapshots + measured age curve (all self-gating)
python "tgs-viz\engine\hitter_tails_fit.py" --league TGS
if errorlevel 1 goto :fail
python "tgs-viz\engine\fielding_curves_fit.py" --league TGS
if errorlevel 1 goto :fail
python "tgs-viz\engine\currency_fit.py" --league TGS
if errorlevel 1 goto :fail
python "tgs-viz\engine\scurve_fit.py" --league TGS
python "tgs-viz\engine\promote_scurves.py" --league TGS
python "tgs-viz\engine\extract_sheet.py" TGS
python "tgs-viz\engine\extract_pitchers.py" TGS
python "tgs-viz\engine\agecurve_fit.py" --league TGS --write
python "tgs-viz\engine\export_calibration.py" --league TGS --write

python "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league TGS --write
if errorlevel 1 goto :fail

rem archive is banked by calibrate above; now delete the spent clone saves.
rem the clone OOTP still has loaded is skipped and swept next cycle.
python "ootp\cleanup_clones.py" --league TGS --junk --yes

if defined STOPAFTER goto :stopped
goto :loop

:stopped
echo.
echo ============================================================
echo   Stopped after a sim problem - everything that finished IS
echo   banked. Check the messages above, fix, and rerun.
echo ============================================================
pause
exit /b 1

:fail
echo.
echo ============================================================
echo   A recalibrate step failed - sim data is still on disk and
echo   in the archive; nothing further was changed. See above.
echo ============================================================
pause
exit /b 1
