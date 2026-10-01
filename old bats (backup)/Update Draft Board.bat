@echo off
title Update Draft Board (TGS + BLM)
cd /d "%~dp0.."

echo ============================================================
echo   DRAFT BOARDS  -  OOTP pool export + StatsPlus ratings
echo ------------------------------------------------------------
echo   Before running, for the league that is drafting:
echo    1. In OOTP: Amateur Draft screen -^> export the DRAFT POOL
echo       report to CSV. (BLM exports hitters and pitchers as two
echo       separate files - both are picked up automatically.)
echo    2. Make sure your ratings pull is recent
echo       ("Get StatsPlus Ratings.bat").
echo   Drafted players drop off automatically from the live
echo   StatsPlus pick list - just re-run this as picks come in.
echo   A league with no pool export is skipped harmlessly.
echo   No Excel needed.
echo ============================================================
echo.

set "FAILS="
echo  --- TGS ---
python "tgs-viz\ingest\draft.py" --league TGS --write
if errorlevel 1 set "FAILS=%FAILS% TGS"
echo.
echo  --- BLM ---
python "tgs-viz\ingest\draft.py" --league BLM --slug blm --write
if errorlevel 1 set "FAILS=%FAILS% BLM"

echo.
echo ============================================================
if defined FAILS goto :notdone
echo   Done. Reload the webapp (switch leagues to see each board).
goto :end
:notdone
echo   NOT updated:%FAILS%
echo   Each one says why above. Fix that, then run this again.
:end
echo ============================================================
pause
