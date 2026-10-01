@echo off
title winsim - TEST the year picker (no clone, no sim)
cd /d "%~dp0.."
set "TGS_PY=python"
python -c "" >nul 2>nul && goto tgs_run
set "TGS_PY=py -3"
py -3 -c "" >nul 2>nul && goto tgs_run
echo.
echo   Python is not installed, or it is not on PATH.
echo   Install Python 3.13 from python.org and tick "Add python.exe to PATH".
echo   Then start this again.
pause
exit /b 9009
:tgs_run
%TGS_PY% "tgs-viz\tools\run_task.py" ootp_test_year_26 %*
set "RC=%errorlevel%"
pause
exit /b %RC%
