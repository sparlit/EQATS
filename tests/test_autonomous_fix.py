import sys
from unittest.mock import MagicMock, patch

import autonomous_fix


def test_run_tests_success() -> None:
    """Tests that run_tests calls subprocess.run with list argument and shell=False (default)."""
    mock_completed_proc = MagicMock()
    mock_completed_proc.returncode = 0

    with patch("subprocess.run", return_value=mock_completed_proc) as mock_run:
        result = autonomous_fix.run_tests()
        assert result is True
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == autonomous_fix.TEST_COMMAND
        assert isinstance(args[0], list)
        assert kwargs.get("shell") is not True


def test_run_tests_failure() -> None:
    """Tests that run_tests returns False on non-zero returncode."""
    mock_completed_proc = MagicMock()
    mock_completed_proc.returncode = 1

    with patch("subprocess.run", return_value=mock_completed_proc) as mock_run:
        result = autonomous_fix.run_tests()
        assert result is False
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == autonomous_fix.TEST_COMMAND
        assert isinstance(args[0], list)
        assert kwargs.get("shell") is not True


def test_main_dependency_install() -> None:
    """Tests that main installs dependencies using list command without shell=True."""
    mock_completed_proc = MagicMock()
    mock_completed_proc.returncode = 0

    with patch("subprocess.run", return_value=mock_completed_proc) as mock_run, \
         patch("autonomous_fix.run_tests", return_value=True):
        try:
            autonomous_fix.main()
        except SystemExit as e:
            assert e.code == 0

        # Check the first call to subprocess.run in main()
        pip_call_args = mock_run.call_args_list[0]
        cmd = pip_call_args[0][0]
        kwargs = pip_call_args[1]
        assert cmd == [sys.executable, "-m", "pip", "install", "pytest-json-report"]
        assert kwargs.get("shell") is not True
