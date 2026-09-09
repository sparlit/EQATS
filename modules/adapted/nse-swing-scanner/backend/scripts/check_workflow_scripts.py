from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


#!/usr/bin/env python3
"""
CI guard: every backend script invoked by GitHub Actions must import cleanly
when run as `python scripts/<name>.py` from cwd=backend with no PYTHONPATH.

Why this exists
---------------
pytest imports modules after injecting backend/ or scripts/ into sys.path.
Workflows do not — they run `python scripts/foo.py` with cwd=backend, so
sys.path[0] is scripts/, not backend/. A script that does
`from performance import ...` (or any backend package import) will pass
unit tests and still crash in Actions with ModuleNotFoundError.

This guard re-runs each workflow entrypoint the same way production does
and fails CI on any import/startup error. Prefer --help so no network I/O
or side effects occur.

Usage:
    python backend/scripts/check_workflow_scripts.py
    # or via the CI workflow step (cwd=backend).
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
SCRIPTS = BACKEND / "scripts"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Match real run lines only (ignore comments): python scripts/name.py
SCRIPT_INVOKE_RE = re.compile(
    r"^\s*python\s+(?:backend/)?scripts/([A-Za-z0-9_\-]+\.py)",
    re.MULTILINE,
)

# Always exercise every file under scripts/ that workflows could grow into.
# Skip this guard itself to avoid recursion.
SKIP = {"check_workflow_scripts.py"}


def discover_workflow_scripts() -> list[str]:
    """Scripts referenced by workflow YAML, union all scripts/*.py."""
    named: set[str] = set()
    if WORKFLOWS.is_dir():
        for yml in WORKFLOWS.glob("*.yml"):
            text = yml.read_text(encoding="utf-8")
            named.update(SCRIPT_INVOKE_RE.findall(text))
    for path in SCRIPTS.glob("*.py"):
        if not path.name.startswith("_"):
            named.add(path.name)
    # Never self-invoke: this guard has no argparse, so `--help` would
    # re-enter main() and recurse until timeout.
    named -= SKIP
    return sorted(named)


def run_script_help(name: str) -> tuple[int, str]:
    """Run `python scripts/<name> --help` with clean env (no PYTHONPATH)."""
    script = SCRIPTS / name
    if not script.is_file():
        return 1, f"script not found: {script}"

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    # --help forces argparse CLIs to exit after import without side effects.
    # Scripts without argparse (e.g. check_cron_consistency) ignore unknown
    # argv and still complete their main() — acceptable for a smoke check.
    proc = subprocess.run(
        [sys.executable, str(Path("scripts") / name), "--help"],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def main() -> int:
    scripts = discover_workflow_scripts()
    if not scripts:
        print("::error::check_workflow_scripts: no scripts discovered")
        return 1

    failed = []
    for name in scripts:
        code, out = run_script_help(name)
        if code != 0:
            failed.append(name)
            print(f"::error::check_workflow_scripts: {name} failed (exit {code})")
            if out.strip():
                print(out.rstrip())
        else:
            print(f"ok  scripts/{name}")

    if failed:
        print(
            f"::error::check_workflow_scripts: {len(failed)} script(s) failed "
            f"under workflow invocation (cwd=backend, no PYTHONPATH): "
            f"{', '.join(failed)}. If the script imports backend modules, "
            f"bootstrap backend/ onto sys.path before those imports "
            f"(see compute_performance.py)."
        )
        return 1

    print(f"check_workflow_scripts: {len(scripts)} script(s) ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
