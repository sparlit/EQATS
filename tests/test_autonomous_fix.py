"""
Unit tests for src/autonomous_fix.py ensuring secure subprocess execution without shell=True.
"""

import contextlib
import sys
from unittest.mock import MagicMock, patch

# Mock openai module if not installed in current environment
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from autonomous_fix import main, run_tests


def test_run_tests_uses_list_args_without_shell():
    with patch("autonomous_fix.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        success = run_tests()
        assert success is True
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert isinstance(args[0], list)
        assert args[0][0] == "python"
        assert args[0][1] == "-m"
        assert args[0][2] == "pytest"
        assert kwargs.get("shell") is not True


def test_main_pip_install_uses_sys_executable_list_without_shell():
    class StopMain(Exception):
        pass

    with patch("autonomous_fix.subprocess.run") as mock_run, \
         patch("autonomous_fix.run_tests", return_value=True), \
         patch("autonomous_fix.sys.exit", side_effect=StopMain) as mock_exit:
        with contextlib.suppress(StopMain):
            main()

        mock_run.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "pytest-json-report"],
            check=True,
        )
        mock_exit.assert_called_once_with(0)
