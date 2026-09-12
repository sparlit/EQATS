#!/usr/bin/env python3
"""
EQATS Quantitative Ingestion Factory - Multi-Repository Autonomous Loop
Tech Stack: Python 3.13 / Rust (PyO3) / Postgres
Strict Zero-Stub Standard Enforcement & Multi-Event Auto-Fixing
"""

import sys
from pathlib import Path

scripts_dir = Path(__file__).resolve().parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from autonomous_repo_integrator import AutonomousRepoIntegrator  # noqa: E402


def main():
    print("[+] Launching EQATS Autonomous Ingestion Factory...")
    integrator = AutonomousRepoIntegrator()
    integrator.run_pipeline(batch_size=1)


if __name__ == "__main__":
    main()
