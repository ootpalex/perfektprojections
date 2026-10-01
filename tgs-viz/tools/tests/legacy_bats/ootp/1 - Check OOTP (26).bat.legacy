@echo off
title winsim - step 1 - check OOTP 26
cd /d "%~dp0.."

echo ============================================================
echo   STEP 1  -  can the tool see your OOTP window?
echo ------------------------------------------------------------
echo   Before you run this:
echo     - open OOTP 26
echo     - leave it on the MAIN MENU (or in a loaded league)
echo ============================================================
echo.

echo --- windows the tool can see (look for "Out of the Park Baseball 26") ---
python "ootp\winsim.py" --game 26 --list-windows
echo.

echo --- taking a screenshot of the OOTP window ---
python "ootp\winsim.py" --game 26 --grab
echo.
echo ============================================================
echo   If you saw the OOTP 26 window listed above and it said
echo   "saved ...winsim_grab.png", you're good. Send that result
echo   (and the ootp\winsim_grab.png file) back to Claude.
echo ============================================================
pause
