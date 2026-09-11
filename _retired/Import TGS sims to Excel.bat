@echo off
title Import TGS sims -> 25 Regressions.xlsx
cd /d "%~dp0.."

echo ============================================================
echo   IMPORT TGS SIMS  ->  The Sheets TGS\25 Regressions.xlsx
echo ------------------------------------------------------------
echo   Finds every clone league you've simmed (that isn't already
echo   imported) and adds its stats under the data already there.
echo   Shows what it will add and asks before writing. A backup
echo   of the workbook is made first.
echo.
echo   CLOSE the workbook in Excel before running this.
echo ============================================================
echo.

python "ootp\ingest_dumps.py" --league TGS --all-new --write

echo.
echo ============================================================
echo   If it added rows: open 25 Regressions.xlsx in Excel,
echo   Data -> Refresh All -> Save.  Then run Sync Regressions.bat.
echo ============================================================
pause
