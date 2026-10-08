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


"""
Tests for paths.py — the anchor that makes runtime state location-independent.

These pin the exact behaviour that a file move would otherwise break silently:
the broker token must resolve to the repository's `data/` directory regardless of
which package the resolving module lives in, and regardless of the process's
working directory.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from shortcircuit import paths

REPO = Path(__file__).resolve().parents[2]


def test_project_root_is_the_repository_root():
    assert paths.PROJECT_ROOT == REPO


def test_root_is_found_by_marker_not_by_relative_depth():
    """
    The whole point: the root is discovered, not computed from how deep this
    file happens to sit. A module moved into src/shortcircuit/broker/ must still
    resolve the same root.
    """
    assert (paths.PROJECT_ROOT / "requirements.txt").exists() or (
        paths.PROJECT_ROOT / "pyproject.toml"
    ).exists()


def test_token_file_resolves_into_the_repository_data_dir():
    """
    Regression guard. `fyers_connect.py` previously used
    Path(__file__).parent / "data" / "access_token.txt", which is correct only
    while that module lives in the repository root. Moving it would have pointed
    the token at a directory inside the package, and the bot would have tried to
    re-authenticate interactively on every start.
    """
    assert paths.TOKEN_FILE == REPO / "data" / "access_token.txt"
    assert "src" not in paths.TOKEN_FILE.parts


@pytest.mark.parametrize(
    "attr,expected",
    [
        ("LOGS_DIR", "logs"),
        ("DATA_DIR", "data"),
        ("REPORTS_DIR", "reports"),
        ("MIGRATIONS_DIR", "migrations"),
    ],
)
def test_runtime_dirs_sit_directly_under_the_root(attr, expected):
    assert getattr(paths, attr) == REPO / expected


def test_ml_dir_is_under_data():
    assert paths.ML_DIR == REPO / "data" / "ml"


def test_every_path_is_absolute():
    """A relative path would reintroduce the CWD dependency this module removes."""
    for name in dir(paths):
        value = getattr(paths, name)
        if isinstance(value, Path) and not name.startswith("_"):
            assert value.is_absolute(), f"{name} is not absolute: {value}"


def test_paths_do_not_depend_on_the_working_directory():
    """
    Resolve the token path from a different CWD in a fresh interpreter. If the
    answer changes, something is still CWD-relative.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(REPO / 'src')!r}); "
            "from shortcircuit import paths; print(paths.TOKEN_FILE)",
        ],
        cwd="/tmp",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(REPO / "data" / "access_token.txt")


def test_root_can_be_overridden_by_environment(monkeypatch, tmp_path):
    """A container or test can relocate state without editing code."""
    monkeypatch.setenv("SHORTCIRCUIT_ROOT", str(tmp_path))
    import importlib

    reloaded = importlib.reload(paths)
    try:
        assert tmp_path.resolve() == reloaded.PROJECT_ROOT
        assert tmp_path.resolve() / "data" / "access_token.txt" == reloaded.TOKEN_FILE
    finally:
        monkeypatch.delenv("SHORTCIRCUIT_ROOT", raising=False)
        importlib.reload(paths)


def test_ensure_runtime_dirs_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("SHORTCIRCUIT_ROOT", str(tmp_path))
    import importlib

    reloaded = importlib.reload(paths)
    try:
        reloaded.ensure_runtime_dirs()
        reloaded.ensure_runtime_dirs()  # must not raise
        assert (tmp_path / "logs" / "fyers_rest").is_dir()
        assert (tmp_path / "data" / "ml").is_dir()
    finally:
        monkeypatch.delenv("SHORTCIRCUIT_ROOT", raising=False)
        importlib.reload(paths)
