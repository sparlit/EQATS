@echo off
echo =============================================================
echo   PURGING ALL LOCAL BRANCHES EXCEPT [MAIN]
echo =============================================================
echo.

:: 1. Move to main branch safely
echo Switching to main branch...
git checkout main

echo.
:: 2. Execute brute-force deletion loop via embedded PowerShell
echo Force-deleting all other branches...
powershell -Command "git branch | ForEach-Object { $_.Trim() } | Where-Object { $_ -notmatch '^\*' -and $_ -ne 'main' } | ForEach-Object { Write-Host 'Deleting:' $_; git branch -D $_ }"

echo.
echo =============================================================
echo Remaining local branches:
git branch
pause
