@echo off
setlocal enabledelayedexpansion

echo =============================================================
echo   NUCLEAR PURGE: ALL PRS ^& 220+ LOCAL BRANCHES
echo =============================================================
echo.

:: --- STEP 1: BULK CLOSE ALL 220+ REMOTE PRS VIA GH CLI ---
echo Requesting all open Pull Requests up to limit (500)...
powershell -Command "$prs = (gh pr list --state open --limit 500 --json number | ConvertFrom-Json); if ($prs) { foreach ($pr in $prs) { Write-Host 'Closing Pull Request #' $pr.number; gh pr close $pr.number | Out-Null } } else { Write-Host 'No open pull requests found.' }"

echo.
:: --- STEP 2: HARD PURGE ALL 221 LOCAL BRANCHES IN BULK ---
echo Switching local repository workspace safely to main/master branch...
git checkout main >nul 2>&1 || git checkout master >nul 2>&1 || git checkout development >nul 2>&1

echo Pruning ghost remote-tracking references...
git fetch --prune --all >nul 2>&1

echo force-deleting all local branches except production baseline...
powershell -Command "$branches = (git branch --format='%(refname:short)'); foreach ($b in $branches) { if ($b -and $b -ne 'main' -and $b -ne 'master' -and $b -ne 'development') { Write-Host 'Force Deleting Local Branch:' $b; git branch -D $b | Out-Null } }"

echo.
echo =============================================================
echo Cleanup complete! Confirming current active tracking count:
git branch
pause
