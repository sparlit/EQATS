@echo off
REM ==============================================================================
# EQATS Auto-PR & Failed Merge Healing Loop Windows Batch Runner
# For Windows 11 Pro CMD / PowerShell
REM ==============================================================================

echo =========================================================================
echo STARTING EQATS AUTO-PR ^& FAILED MERGE HEALING ENGINE (WINDOWS 11 PRO)
echo =========================================================================

if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python .github\scripts\auto_pr_healer.py %*

echo =========================================================================
echo AUTO-PR HEALING LOOP FINISHED ON WINDOWS 11 PRO
echo =========================================================================
