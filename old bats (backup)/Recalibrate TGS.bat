@echo off
title TGS - Recalibrate from clone sims (Python, no Excel)
cd /d "%~dp0.."

echo ============================================================
echo   RECALIBRATE TGS  -  clone sims  -^>  regression constants
echo                      -^>  projection sheets  -^>  webapp data
echo ------------------------------------------------------------
echo   1. Computes every regression constant from the clone dumps
echo      on disk (C:\OOTP 26\data\saved_games\*tgs*.lg).
echo      Incomplete clones are skipped automatically.
echo   2. Shows you exactly what would change in the sheets and
echo      asks before writing (timestamped .bak made first).
echo   3. Rebuilds the webapp data from the cached StatsPlus pull.
echo   No Excel needed. Takes ~30 seconds total.
echo   (Sim more clones first with "4 - Sim TGS.bat" if you want
echo    a bigger sample.)
echo ============================================================
echo.
pause

python "tgs-viz\engine\calibrate.py" --csv-dir "tgs-viz\engine\calib\TGS" --dumps "C:/OOTP 26/data/saved_games/*tgs*.lg" --ratings-dir "tgs-viz\engine\calib\TGS" --json "tgs-viz\engine\calib\TGS\constants-latest.json" --archive-dir "tgs-viz\engine\calib\TGS"
if errorlevel 1 goto :fail

python "tgs-viz\ingest\sync_datapoints.py" --league TGS --calib "tgs-viz\engine\calib\TGS\constants-latest.json" --write
if errorlevel 1 goto :fail

rem Phase B fitted layers (D4 hitter tails + D3 fielding curves) - refit from the
rem new archive/constants so the live engine layers stay in step.
python "tgs-viz\engine\hitter_tails_fit.py" --league TGS
if errorlevel 1 goto :fail
python "tgs-viz\engine\fielding_curves_fit.py" --league TGS
if errorlevel 1 goto :fail
rem D2/D9 currency layer (RA/9 exponents, RPW, workloads, luck SD) - refit from
rem the same archive so the $ layer and win models track the new constants.
rem (Keeps the existing rp_shrink block; was an orphaned manual step before.)
python "tgs-viz\engine\currency_fit.py" --league TGS
if errorlevel 1 goto :fail

rem D1 S-curves: refit the preview, then gate-checked AUTO-promotion (promote_scurves.py)
python "tgs-viz\engine\scurve_fit.py" --league TGS
python "tgs-viz\engine\promote_scurves.py" --league TGS
python "tgs-viz\engine\export_calibration.py" --league TGS --write
if errorlevel 1 goto :fail

rem Refresh the read-back snapshots so the drift check stays quiet.
python "tgs-viz\engine\extract_sheet.py" TGS
python "tgs-viz\engine\extract_pitchers.py" TGS

python "tgs-viz\ingest\refresh.py" --statsplus --from-cache --league TGS --write
if errorlevel 1 goto :fail

echo.
echo   Clone data is archived - the clone leagues can be deleted now
echo   (your real leagues are never touched; answer N to keep them).
python "ootp\cleanup_clones.py" --league TGS --junk

echo.
echo ============================================================
echo   Done. Reload the webapp. Your Excel sheets recalc with the
echo   new constants next time you open them (no Refresh All).
echo ============================================================
pause
exit /b 0

:fail
echo.
echo   Something failed above - nothing further was changed.
pause
exit /b 1
