@echo off
title winsim - grab a menu (OOTP 26)
cd /d "%~dp0.."

echo ============================================================
echo   GRAB A MENU  (OOTP 26)
echo ------------------------------------------------------------
echo   This brings OOTP to the front, then counts down 6 seconds.
echo   DURING the countdown, open the menu Claude asked for
echo   (e.g. click FILE, or click PLAY) and LEAVE it open.
echo   It screenshots while the menu is still showing.
echo ============================================================
echo.
pause

python "ootp\winsim.py" --game 26 --grab --delay 6

echo.
echo ============================================================
echo   Saved to ootp\winsim_grab.png  -  send it to Claude.
echo ============================================================
pause
