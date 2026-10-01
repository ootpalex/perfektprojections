@echo off
title TGS Projections
cd /d "%~dp0tgs-viz"

echo ========================================
echo   TGS Projections - Starting...
echo ========================================
echo.

where node >nul 2>nul
if errorlevel 1 (
  echo   Node.js is not installed, or it is not on PATH.
  echo   Install Node.js 22 LTS from nodejs.org, then start this again.
  pause
  exit /b 1
)

if not exist "node_modules\.bin\vite.cmd" (
  echo   The app's packages are not installed yet.
  echo   Open a terminal in the tgs-viz folder and run:  npm install
  echo   Then start this again.
  pause
  exit /b 1
)

:: Start the dev server (opens browser automatically)
call npx vite --port 3000 --strictPort --open
if errorlevel 1 (
  echo.
  echo   The app stopped. If the message above says port 3000 is in use,
  echo   the app may already be running: use its browser tab, or close the
  echo   other TGS Projections window first.
  echo   If no other TGS window is open, another program is using port 3000. Close it.
  pause
)
