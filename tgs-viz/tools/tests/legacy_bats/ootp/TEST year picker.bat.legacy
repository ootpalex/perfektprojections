@echo off
title winsim - TEST the year picker (no clone, no sim)
cd /d "%~dp0.."

echo ============================================================
echo   TEST YEAR PICKER  (diagnostic - safe)
echo ------------------------------------------------------------
echo   Have OOTP 26 open with ANY league loaded (Baseline is fine
echo   to just LOOK at - this never sims or clicks AUTO-PLAY).
echo   It opens Play -^> Specified Date and tries to set the year,
echo   then STOPS and saves screenshots for Claude.
echo   Keep hands off once it starts. Corner-slam to abort.
echo ============================================================
echo.
pause
python "ootp\winsim.py" --league TGS --test-year
echo.
echo ============================================================
echo   Done. Send Claude the text above, or just say "done" and
echo   Claude will read the ootp\_diag_*.png snapshots.
echo ============================================================
pause
