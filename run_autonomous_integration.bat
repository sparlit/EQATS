@echo off
REM ==============================================================================
# EQATS Autonomous Repository Integrator & Self-Healing Loop Windows Batch Runner
# For Windows 11 Pro OS / Windows Subsystem for Linux / Command Prompt
REM ==============================================================================

echo =========================================================================
echo EQATS AUTONOMOUS REPOSITORY INTEGRATION ENGINE (WINDOWS 11 PRO)
echo =========================================================================

REM Check Python Installation
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] Error: Python was not found in PATH. Please install Python 3.12+ on Windows 11.
    exit /b 1
)

REM Activate Virtual Environment if present
if exist ".venv\Scripts\activate.bat" (
    echo [+] Activating Windows virtual environment .venv...
    call .venv\Scripts\activate.bat
)

REM Ensure required module directories exist
if not exist "modules\adapted" mkdir modules\adapted
if not exist "src\institutional_integrations" mkdir src\institutional_integrations

REM Execute Python Autonomous Integrator
echo [+] Launching Autonomous Integration ^& Self-Healing Pipeline...
python .github\scripts\autonomous_repo_integrator.py %*

echo =========================================================================
echo POST-INTEGRATION QUALITY CHECK
echo =========================================================================

where ruff >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [*] Running Ruff Linter over adapted modules...
    python -m ruff check modules\adapted\
)

where mypy >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [*] Running Mypy Type Checker over adapted modules...
    python -m mypy modules\adapted\ --check-untyped-defs
)

echo =========================================================================
echo SUCCESS: Autonomous Integration Cycle Finished on Windows 11.
echo =========================================================================
