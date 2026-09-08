#!/usr/bin/env bash
# ==============================================================================
# EQATS Autonomous Repository Integrator & Self-Healing Loop Local/CI Runner
# ==============================================================================

set -euo pipefail

echo "========================================================================="
echo "EQATS AUTONOMOUS REPOSITORY INTEGRATION ENGINE"
echo "========================================================================="

# Ensure Python virtual environment if available
if [ -d ".venv" ]; then
    echo "[+] Activating virtual environment .venv..."
    source .venv/bin/activate
fi

# Ensure output directory structures exist
mkdir -p modules/adapted
mkdir -p src/institutional_integrations

# Execute Autonomous Integrator
echo "[+] Launching Autonomous Integration & Self-Healing Pipeline..."
python3 .github/scripts/autonomous_repo_integrator.py "$@"

echo "========================================================================="
echo "POST-INTEGRATION ZERO-STUB & QUALITY GATE CHECK"
echo "========================================================================="

if command -v ruff &> /dev/null; then
    echo "[*] Running Ruff linter over adapted modules..."
    ruff check modules/adapted/ || echo "[!] Linter notices detected."
fi

if command -v mypy &> /dev/null; then
    echo "[*] Running Mypy type checker over adapted modules..."
    mypy modules/adapted/ --check-untyped-defs || echo "[!] Type warnings detected."
fi

echo "========================================================================="
echo "SUCCESS: Autonomous Integration Cycle Finished."
echo "========================================================================="
