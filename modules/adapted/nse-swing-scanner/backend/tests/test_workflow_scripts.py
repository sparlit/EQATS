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


"""Tests for backend/scripts/check_workflow_scripts.py CI guard."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, ".."))
SCRIPTS_DIR = os.path.join(BACKEND_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import check_workflow_scripts  # noqa: E402


class TestDiscover(unittest.TestCase):
    def test_includes_workflow_entrypoints(self):
        names = check_workflow_scripts.discover_workflow_scripts()
        for required in (
            "check_cron_consistency.py",
            "compute_performance.py",
            "send_digest.py",
            "snapshot_writer.py",
            "watchdog_check.py",
        ):
            assert required in names
        assert "check_workflow_scripts.py" not in names


class TestGuardMain(unittest.TestCase):
    def test_main_exits_zero(self):
        assert check_workflow_scripts.main() == 0

    def test_subprocess_matches_ci_invocation(self):
        """Same command line as ci.yml (cwd=backend, no PYTHONPATH)."""
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        proc = subprocess.run(
            [sys.executable, "scripts/check_workflow_scripts.py"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr


if __name__ == "__main__":
    unittest.main()
