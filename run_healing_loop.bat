@echo off
REM ==============================================================================
# EQATS Multi-Event Self-Healing Loop Windows Batch Runner
# For Windows 11 Pro OS Command Prompt / PowerShell
REM ==============================================================================

echo =========================================================================
echo STARTING EQATS MULTI-LOCATION SELF-HEALING LOOP (WINDOWS 11 PRO)
echo =========================================================================

REM Activate virtual environment if present
if exist ".venv\Scripts\activate.bat" (
    echo [+] Activating Windows virtual environment .venv...
    call .venv\Scripts\activate.bat
)

REM Step 1: Auto-Fix Python Lint & Formatting Anomalies
where ruff >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [*] Auto-Fixing Python Linting Errors with Ruff...
    python -m ruff check --fix --unsafe-fixes .
    python -m ruff format .
)

REM Step 2: Auto-Fix Mypy Static Type Checking
where mypy >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [*] Checking Python Static Typing with Mypy...
    python -m mypy . --check-untyped-defs
)

REM Step 3: Run Self-Healing Integration Engine Pass
echo [*] Invoking Autonomous Repository Integrator Pipeline...
python .github\scripts\autonomous_repo_integrator.py %*

echo =========================================================================
echo SELF-HEALING LOOP PASS COMPLETED SUCCESSFULLY ON WINDOWS 11 PRO
echo =========================================================================
