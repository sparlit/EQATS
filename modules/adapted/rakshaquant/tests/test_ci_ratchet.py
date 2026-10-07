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


"""The CI mypy ratchet (scripts/ci/mypy_ratchet.py) must never pass an incomplete mypy run."""

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "mypy_ratchet.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mypy_ratchet_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(stdout: str, returncode: int, ceiling: str = "374") -> int:
    fake = subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")
    with patch("subprocess.run", return_value=fake):
        return int(_load().main([ceiling]))


@pytest.mark.parametrize(
    ("stdout", "returncode", "expected"),
    [
        ("Found 374 errors in 39 files (checked 79 source files)\n", 1, 0),
        ("Found 12 errors in 3 files (checked 79 source files)\n", 1, 0),
        ("Success: no issues found in 79 source files\n", 0, 0),
        ("Found 375 errors in 39 files (checked 79 source files)\n", 1, 1),
        # A blocking error stops mypy early: "1 error" must not pass under the ceiling.
        (
            "x.py:1: error: Invalid syntax\nFound 1 error in 1 file (errors prevented further checking)\n",
            2,
            1,
        ),
        ("garbage\n", 1, 1),
    ],
)
def test_ratchet_outcomes(stdout, returncode, expected):
    assert _run(stdout, returncode) == expected


def test_bad_usage_exits_2():
    assert _load().main([]) == 2
    assert _load().main(["many"]) == 2
