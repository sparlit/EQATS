@echo off
setlocal enabledelayedexpansion

echo =============================================================
echo   BRUTE-FORCE BRANCH PURGE (EXCEPT MAIN)
echo =============================================================
echo.

:: 1. Force move to the main branch
echo Ensuring workspace is on main...
git checkout main

echo.
echo Gathering clean branch references and executing force-delete...
echo -------------------------------------------------------------

:: 2. Pull raw branch references directly out of the Git database
for /f "tokens=*" %%B in ('git for-each-ref --format="%%(refname:short)" refs/heads/') do (
    set "BRANCH=%%B"
    
    :: Remove remote prefixes if present to isolate the exact name
    set "CLEAN_BRANCH=!BRANCH:origin/=!"
    
    :: Skip the main branch explicitly
    if not "!CLEAN_BRANCH!"=="main" (
        echo Force Deleting: [!CLEAN_BRANCH!]
        git branch -D !CLEAN_BRANCH!
    )
)

echo.
echo =============================================================
echo Remaining local branches:
git branch
pause
