@echo off
title BLM - Recalibrate from clone sims (Python, no Excel)
cd /d "%~dp0"

echo ============================================================
echo   RECALIBRATE BLM  -  archived sample + any new clone sims
echo                      -^>  constants  -^>  sheets  -^>  webapp
echo ------------------------------------------------------------
echo   Pools the archived BLM calibration sample (in
echo   tgs-viz\engine\calib\BLM) together with any NEW complete
echo   clone sims in OOTP 27's saved_games (0blm*.lg).
echo   Shows what would change and asks before writing (.bak
echo   made automatically). Then rebuilds the webapp data.
echo   No Excel needed.
echo ============================================================
echo.
pause

python "tgs-viz\engine\calibrate.py" --csv-dir "tgs-viz\engine\calib\BLM" --dumps "%USERPROFILE%/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games/0blm*.lg" --ratings-dir "tgs-viz\engine\calib\BLM" --json "tgs-viz\engine\calib\BLM\constants-latest.json" --archive-dir "tgs-viz\engine\calib\BLM"
if errorlevel 1 goto :fail

python "tgs-viz\ingest\sync_datapoints.py" --league BLM --calib "tgs-viz\engine\calib\BLM\constants-latest.json" --write
if errorlevel 1 goto :fail

rem Phase B fitted layers (D4 hitter tails + D3 fielding curves) - refit from the
rem new archive/constants so the live engine layers stay in step.
python "tgs-viz\engine\hitter_tails_fit.py" --league BLM
if errorlevel 1 goto :fail
python "tgs-viz\engine\fielding_curves_fit.py" --league BLM
if errorlevel 1 goto :fail
rem D2/D9 currency layer (RA/9 exponents, RPW, workloads, luck SD) - refit from
rem the same archive so the $ layer and win models track the new constants.
rem (Keeps the existing rp_shrink block; was an orphaned manual step before.)
python "tgs-viz\engine\currency_fit.py" --league BLM
if errorlevel 1 goto :fail

rem D1 S-curves: PREVIEW ONLY for BLM (ratings were re-scouted mid-season after
rem the metadata anchors; the live flip waits for the season-end rebuild - see
rem ratings.live_scurves for the promotion procedure).
python "tgs-viz\engine\scurve_fit.py" --league BLM
python "tgs-viz\engine\export_calibration.py" --league BLM --write
if errorlevel 1 goto :fail

rem Refresh the read-back snapshots so the drift check stays quiet.
python "tgs-viz\engine\extract_sheet.py" BLM
python "tgs-viz\engine\extract_pitchers.py" BLM

python "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league BLM --slug blm --write
if errorlevel 1 goto :fail

echo.
echo   Clone data is archived - the clone leagues can be deleted now
echo   (your real leagues are never touched; answer N to keep them).
python "ootp\cleanup_clones.py" --league BLM --junk

echo.
echo ============================================================
echo   Done. Reload the webapp.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo   Something failed above - nothing further was changed.
pause
exit /b 1
