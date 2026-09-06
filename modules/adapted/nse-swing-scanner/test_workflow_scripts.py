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
        ):
            self.assertIn(required, names)
        self.assertNotIn("check_workflow_scripts.py", names)


class TestGuardMain(unittest.TestCase):
    def test_main_exits_zero(self):
        self.assertEqual(check_workflow_scripts.main(), 0)

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
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
