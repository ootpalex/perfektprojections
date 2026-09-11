@echo off
title TGS - Updating Data
cd /d "%~dp0tgs-viz"

echo ========================================
echo   TGS Projections - Updating Data
echo ========================================
echo.
echo Scanning for league folders...
echo.

python extract_data.py

echo.
echo ========================================
echo   Done! You can close this window.
echo   Refresh your browser to see new data.
echo ========================================
pause
