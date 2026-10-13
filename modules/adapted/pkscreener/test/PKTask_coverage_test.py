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


"""
    The MIT License (MIT)

    Copyright (c) 2023 pkjmesra

    Tests for PKTask.py to achieve 100% coverage.
"""

import warnings

import pytest

warnings.filterwarnings("ignore")


class TestPKTaskCoverage:
    """Comprehensive tests for PKTask."""

    def test_pktask_init_valid(self):
        """Test PKTask initialization with valid args."""
        from pkscreener.classes.PKTask import PKTask

        def my_func():
            pass

        task = PKTask("Test Task", my_func, ("arg1",))

        assert task.taskName == "Test Task"
        assert task.long_running_fn == my_func
        assert task.long_running_fn_args == ("arg1",)

    def test_pktask_init_none_task_name(self):
        """Test PKTask raises ValueError for None taskName."""
        from pkscreener.classes.PKTask import PKTask

        with pytest.raises(ValueError, match="taskName cannot be None"):
            PKTask(None, lambda: None)

    def test_pktask_init_empty_task_name(self):
        """Test PKTask raises ValueError for empty taskName."""
        from pkscreener.classes.PKTask import PKTask

        with pytest.raises(ValueError, match="taskName cannot be None"):
            PKTask("", lambda: None)

    def test_pktask_init_none_fn(self):
        """Test PKTask raises ValueError for None long_running_fn."""
        from pkscreener.classes.PKTask import PKTask

        with pytest.raises(ValueError, match="long_running_fn cannot be None"):
            PKTask("Valid Name", None)

    def test_pktask_default_values(self):
        """Test PKTask has correct default values."""
        from pkscreener.classes.PKTask import PKTask

        task = PKTask("Test", lambda: None)

        assert task.progressStatusDict is None
        assert task.taskId == 0
        assert task.progress == 0
        assert task.total == 0
        assert task.resultsDict is None
        assert task.result is None
        assert task.userData is None

    def test_pktask_with_progress_fn(self):
        """Test PKTask with progress function."""
        from pkscreener.classes.PKTask import PKTask

        def progress():
            pass

        task = PKTask("Test", lambda: None, None, progress)

        assert task.progress_fn == progress
