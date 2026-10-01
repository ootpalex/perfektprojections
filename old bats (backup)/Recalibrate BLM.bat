@echo off
title BLM - Recalibrate (real-season metadata + regressions from the BLM clone archive)
cd /d "%~dp0.."
echo ============================================================
echo   RECALIBRATE BLM  -  metadata + regressions  -^>  sheets  -^>  webapp
echo ------------------------------------------------------------
echo   Two layers, one run:
echo   A. METADATA = the real BLM season. StatsPlus stats API + your
echo      season-end ratings pull build 7 of the 9 input tabs. Run
echo      "Get StatsPlus Ratings" first so the pull is the season-end one.
echo      YOU paste the pitchers' AS-STARTER stats into 'SP Data' and
echo      AS-RELIEVER stats into 'RP Data' in The Sheets BLM\25 Metadata
echo      .xlsx (StatsPlus has no stats split by role). Your paste is
echo      used as it is.
echo   B. REGRESSIONS = clone sims run with BLM's league settings. Pools
echo      the archived sample (tgs-viz\engine\calib\BLM) with any NEW
echo      complete clone sims in OOTP 27's saved_games (0blm*.lg). It
echo      runs AFTER the metadata because the pitching intercepts are
echo      stated at the league-average ratings the metadata just moved.
echo      This step never sims anything itself.
echo   Then: moves both into The Sheet Hitters / Pitchers (backups made,
echo   every change listed), refits the fitted layers, promotes the
echo   S-curves if they pass their gates, rebuilds the webapp data.
echo   It does not stop to ask. Running it means update everything.
echo ============================================================
echo.
pause
set "INPUTS=tgs-viz\engine\calib\BLM\metadata_inputs"
set "META=tgs-viz\engine\calib\BLM\metadata-latest.json"
set "CONST=tgs-viz\engine\calib\BLM\constants-latest.json"
echo.
echo  --- A1. metadata inputs from StatsPlus ---
python "tgs-viz\ingest\metadata_inputs.py" --league BLM --out "%INPUTS%" --stage auto
if errorlevel 1 goto :fail
echo.
echo  ============================================================
echo   REMINDER: paste 'SP Data' (as starter) and 'RP Data' (as
echo   reliever) into  The Sheets BLM\25 Metadata.xlsx,  save, and
echo   CLOSE Excel. Already done? Just press a key.
echo  ============================================================
pause
echo.
echo  --- A2. your SP/RP paste ---
python "tgs-viz\ingest\metadata_inputs.py" --league BLM --out "%INPUTS%" --stage roles --accept-paste
if errorlevel 1 goto :fail
echo.
echo  --- A3. metadata Data Points (Python port of 25 Metadata) ---
python "tgs-viz\engine\metadata_calibrate.py" --inputs-dir "%INPUTS%" --json "%META%"
if errorlevel 1 goto :fail
echo.
echo  --- B. regressions from the BLM clone archive, centred on the NEW anchors ---
python "tgs-viz\engine\calibrate.py" --csv-dir "tgs-viz\engine\calib\BLM" --dumps "%USERPROFILE%/Documents/Out of the Park Developments/OOTP Baseball 27/saved_games/0blm*.lg" --ratings-dir "tgs-viz\engine\calib\BLM" --json "%CONST%" --archive-dir "tgs-viz\engine\calib\BLM"
if errorlevel 1 goto :fail
echo.
echo  --- move the metadata + regressions into The Sheet Hitters / Pitchers (backups made) ---
python "tgs-viz\ingest\sync_datapoints.py" --league BLM --calib "%CONST%" --metadata-calib "%META%" --write --yes
if errorlevel 1 goto :fail
rem Fitted layers (archive-fitted). The S-curve fit centres on the pitcher
rem anchors, which now come from metadata-latest.json.
python "tgs-viz\engine\hitter_tails_fit.py" --league BLM
if errorlevel 1 goto :fail
python "tgs-viz\engine\fielding_curves_fit.py" --league BLM
if errorlevel 1 goto :fail
python "tgs-viz\engine\currency_fit.py" --league BLM
if errorlevel 1 goto :fail
python "tgs-viz\engine\scurve_fit.py" --league BLM
python "tgs-viz\engine\promote_scurves.py" --league BLM
python "tgs-viz\engine\export_calibration.py" --league BLM --write
if errorlevel 1 goto :fail
rem Refresh the read-back snapshots so the drift check stays quiet.
python "tgs-viz\engine\extract_sheet.py" BLM
python "tgs-viz\engine\extract_pitchers.py" BLM
echo.
echo  --- webapp data from the cached pull with the new constants ---
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
