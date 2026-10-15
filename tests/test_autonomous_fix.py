import sys
from unittest.mock import MagicMock, patch

import pytest

from autonomous_fix import TEST_ARGS, main, run_tests


def test_run_tests_executes_safely_without_shell() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        success = run_tests()
        assert success is True
        mock_run.assert_called_once_with([sys.executable] + TEST_ARGS, check=False)
        # Ensure shell argument is not passed or False
        _, kwargs = mock_run.call_args
        assert kwargs.get("shell") is not True


def test_main_pip_install_executes_safely_without_shell() -> None:
    with (
        patch("subprocess.run") as mock_run,
        patch("autonomous_fix.run_tests", return_value=True),
        patch("sys.exit", side_effect=SystemExit(0)) as mock_exit,
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0
        mock_run.assert_called_once_with(
            [sys.executable, "-m", "pip", "install", "pytest-json-report"],
            check=False,
        )
        _, kwargs = mock_run.call_args
        assert kwargs.get("shell") is not True
        mock_exit.assert_called_once_with(0)
