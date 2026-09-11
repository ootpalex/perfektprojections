@echo off
title TGS - Sync Data Points (Metadata -> Sheets)
cd /d "%~dp0"

echo ============================================================
echo   Sync Data Points  -  Metadata  ^-^>  Sheets
echo ============================================================
echo.
echo   Use this after you refresh 25 Metadata.xlsx with new
echo   league exports: open it in Excel, recalculate, and SAVE
echo   (for BOTH The Sheets BLM and The Sheets TGS).
echo.
echo   This copies the metadata constants (anchors, league rates,
echo   fielding ratings, positional adjustments) into The Sheet
echo   Hitters/Pitchers "Data Points" tabs. The REGRESSION half
echo   always comes from the Python calibration (constants-latest
echo   .json), NOT from 25 Regressions.xlsx - so this can never
echo   overwrite a calibration. It shows every change and asks
echo   before writing. Your next "Get StatsPlus Ratings" pull
echo   then updates the web app.
echo.
echo ============================================================
echo.

python "tgs-viz\ingest\sync_datapoints.py" --league TGS --calib "tgs-viz\engine\calib\TGS\constants-latest.json" --write
if errorlevel 1 goto :fail

python "tgs-viz\ingest\sync_datapoints.py" --league BLM --calib "tgs-viz\engine\calib\BLM\constants-latest.json" --write
if errorlevel 1 goto :fail

rem Refresh the read-back snapshots so the drift check stays quiet.
python "tgs-viz\engine\extract_sheet.py" TGS
python "tgs-viz\engine\extract_pitchers.py" TGS
python "tgs-viz\engine\extract_sheet.py" BLM
python "tgs-viz\engine\extract_pitchers.py" BLM

echo.
echo ============================================================
echo   Done. Run "Get StatsPlus Ratings.bat" to rebuild the app
echo   data, then refresh your browser.
echo ============================================================
pause
exit /b 0

:fail
echo.
echo   Something failed above - nothing further was changed.
pause
exit /b 1
