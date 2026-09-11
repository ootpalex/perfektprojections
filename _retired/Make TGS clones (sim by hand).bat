@echo off
title winsim - make TGS clones (you sim them by hand)
cd /d "%~dp0.."

echo ============================================================
echo   MAKE TGS CLONES  -  no mouse takeover, no OOTP driving
echo ------------------------------------------------------------
echo   Makes fresh copies of your pristine Baseline league so you
echo   can load each one in OOTP and auto-play it yourself.
echo   (Each copy is ~75 MB.)
echo ============================================================
echo.
set /p N=How many clones to make? (e.g. 3):
if "%N%"=="" set N=1

python "ootp\winsim.py" --league TGS --runs %N% --clone-only

echo.
echo ============================================================
echo   Now in OOTP 26: load each tgs-run** league and auto-play
echo   it to Jan 1, 2026. Then run:
echo       "Import TGS sims to Excel.bat"
echo ============================================================
pause
