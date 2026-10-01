@echo off
title BLM GRIND - sim + recalibrate on repeat (close this window to stop)
cd /d "%~dp0.."

echo ============================================================
echo   BLM GRIND  -  fully automatic, runs until YOU stop it
echo ------------------------------------------------------------
echo   Each cycle: 10 clones of master "6" x 10 seasons, then it
echo   AUTOMATICALLY recalibrates BLM (constants -^> sheets -^>
echo   webapp), refreshes the fitted layers, archives the season
echo   data and deletes the spent clone saves. Then repeats.
echo.
echo   START STATE: OOTP 27 open INSIDE any league EXCEPT the
echo   master "6". Then hands off the mouse/keyboard.
echo   (Grind TGS and Grind BLM cannot run at the same time -
echo    they share your mouse.)
echo.
echo   STOP: close this window (or Ctrl+C). Every finished cycle
echo   is already banked.
echo ============================================================
echo.
pause

set CYCLE=0

:loop
set /a CYCLE+=1
echo.
echo ################  BLM CYCLE %CYCLE%  -  simming 10 clones (~100 seasons)  ################
python "ootp\winsim.py" --league BLM --runs 10
if errorlevel 1 (
    echo   winsim reported a problem - recalibrating what finished, then stopping.
    set STOPAFTER=1
)

echo.
echo ################  BLM CYCLE %CYCLE%  -  recalibrating  ################
python "tgs-viz\engine\calibrate.py" --csv-dir "tgs-viz\engine\calib\BLM" --dumps "%USERPROFILE%/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games/0blm*.lg" --ratings-dir "tgs-viz\engine\calib\BLM" --json "tgs-viz\engine\calib\BLM\constants-latest.json" --archive-dir "tgs-viz\engine\calib\BLM"
if errorlevel 1 goto :fail

python "tgs-viz\ingest\sync_datapoints.py" --league BLM --calib "tgs-viz\engine\calib\BLM\constants-latest.json" --write --yes
if errorlevel 1 goto :fail

rem fitted layers + snapshots + measured age curve (all self-gating)
python "tgs-viz\engine\hitter_tails_fit.py" --league BLM
if errorlevel 1 goto :fail
python "tgs-viz\engine\fielding_curves_fit.py" --league BLM
if errorlevel 1 goto :fail
python "tgs-viz\engine\currency_fit.py" --league BLM
if errorlevel 1 goto :fail
rem S-curves: PREVIEW ONLY for BLM. League policy keeps BLM on the sheet's
rem two-segment lines until its season-end rebuild (mid-season re-scout).
rem No promote step here - flipping BLM to S-curves is a decision, not a chore.
python "tgs-viz\engine\scurve_fit.py" --league BLM
python "tgs-viz\engine\extract_sheet.py" BLM
python "tgs-viz\engine\extract_pitchers.py" BLM
python "tgs-viz\engine\agecurve_fit.py" --league BLM --write
python "tgs-viz\engine\export_calibration.py" --league BLM --write

python "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league BLM --slug blm --write
if errorlevel 1 goto :fail

rem archive is banked by calibrate above; now delete the spent clone saves.
rem the clone OOTP still has loaded is skipped and swept next cycle.
python "ootp\cleanup_clones.py" --league BLM --junk --yes

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
