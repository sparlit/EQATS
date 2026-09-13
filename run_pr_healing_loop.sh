#!/usr/bin/env bash
# ==============================================================================
# EQATS Auto-PR & Failed Merge Healing Loop POSIX Runner
# ==============================================================================

set -euo pipefail

echo "========================================================================="
echo "STARTING EQATS AUTO-PR & FAILED MERGE HEALING ENGINE"
echo "========================================================================="

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python3 .github/scripts/auto_pr_healer.py "$@"

echo "========================================================================="
echo "AUTO-PR HEALING LOOP FINISHED"
echo "========================================================================="
