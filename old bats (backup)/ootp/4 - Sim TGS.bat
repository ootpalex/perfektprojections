@echo off
title winsim - TGS  (real run)
cd /d "%~dp0..\.."

echo ============================================================
echo   SIM TGS  -  clones your Baseline league and auto-plays it
echo ------------------------------------------------------------
echo   * Have OOTP 26 open INSIDE a league (any league EXCEPT the
echo     Baseline master - the tool needs FILE-^>Load Game, and the
echo     master must be closed so its files can be copied),
echo     and NOT running as administrator
echo     (if it is, the tool can't click it - see Claude's note).
echo   * Runs 10 clones back-to-back (~10 seasons each, ~7-8 min
echo     per clone with the new Baseline). Edit --runs to change.
echo   * ABORT any time: slam the mouse into a screen corner.
echo   * Do not touch the mouse/keyboard once it starts clicking.
echo ============================================================
echo.
pause
python "ootp\winsim.py" --league TGS --runs 10
echo.
echo ============================================================
echo   Done. Next: "Recalibrate TGS.bat" (repo root) pools the new
echo   clones into the constants and rebuilds the app data.
echo ============================================================
pause
