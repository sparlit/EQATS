@echo off
setlocal enabledelayedexpansion

echo =============================================================
echo   DIAGNOSTIC & FORCE PR PURGE 
echo =============================================================
echo.

echo Checking connection to GitHub...
gh api user --jq .login
if %errorlevel% neq 0 (
    echo [ERROR] You are not logged into the GitHub CLI.
    echo Please run: gh auth login
    pause
    exit /b 1
)

echo.
echo Checking exact number of open PRs...
gh pr list --state open --limit 500 --json number --jq "length"

echo.
echo Closing all open PRs in bulk...
:: Loops through PR numbers directly via plain text generation without temp files
for /f %%A in ('gh pr list --state open --limit 500 --json number --jq ".[] | .number"') do (
    echo Closing PR #%%A...
    gh pr close %%A
)

echo.
echo =============================================================
echo   PURGING LOCAL AND REMOTE BRANCHES
echo =============================================================
echo.

echo Switching to safety branch...
git checkout main || git checkout master || git checkout development

echo.
echo Fetching and pruning remote references...
git fetch --prune --all

echo.
echo Force-deleting all local branches except your current one...
:: Using powershell inside batch to safely loop local branches without crashing
powershell -Command "git branch | ForEach-Object { $_.Trim() } | Where-Object { -not $_.StartsWith('*') -and $_ -ne 'main' -and $_ -ne 'master' } | ForEach-Object { git branch -D $_ }"

echo.
echo =============================================================
echo Process executed. Please review the output above for any errors.
pause
