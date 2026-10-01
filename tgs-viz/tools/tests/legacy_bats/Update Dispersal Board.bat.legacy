@echo off
title TGS - Dispersal Draft Board
cd /d "%~dp0"

echo ============================================================
echo   TGS DISPERSAL DRAFT BOARD
echo ------------------------------------------------------------
echo   Pool = every player in the four folding orgs:
echo     Atlanta Hammers / Detroit Tigers /
echo     San Francisco Giants / Seattle Mariners
echo   Ratings come from the cached StatsPlus pull (run
echo   "Get StatsPlus Ratings.bat" first if it's stale).
echo   As picks happen, add each drafted player's name to
echo   dispersal_drafted.txt (one per line) and re-run this.
echo   No Excel, no OOTP export needed.
echo ============================================================
echo.

python "tgs-viz\ingest\draft.py" --league TGS --orgs "Atlanta Hammers,Detroit Tigers,San Francisco Giants,Seattle Mariners" --write
if errorlevel 1 goto :notdone

echo.
echo   Done. Reload the webapp - the Draft tab is now the dispersal pool.
goto :end
:notdone
echo.
echo   NOT updated. The reason is above. Fix that, then run this again.
:end
pause
