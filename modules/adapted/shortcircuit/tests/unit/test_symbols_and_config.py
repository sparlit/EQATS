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
Tests for symbols.py, market_utils.py and config.py.

The config tests are the important ones: they assert that no secret ships with a
usable default. A credential with a working fallback value is how a repository
ends up authenticating from a machine nobody expected.
"""

from datetime import datetime, timedelta, timezone

import pytest
from freezegun import freeze_time
from shortcircuit import config
from shortcircuit.marketdata import market_utils, symbols

IST = timezone(timedelta(hours=5, minutes=30))


# symbols.py


@pytest.mark.parametrize(
    "sym",
    [
        "NSE:SBIN-EQ",
        "NSE:NIFTY50-INDEX",
        "NSE:RELIANCE-EQ",
        "NSE:NIFTYBANK-INDEX",
    ],
)
def test_valid_fyers_symbols_accepted(sym):
    assert symbols.validate_symbol(sym) is True


@pytest.mark.parametrize(
    "sym",
    [
        "SBIN",  # no exchange prefix
        "NSE:SBIN",  # no series suffix
        "",  # empty
        None,  # missing
        "NSE:EXTRA:SBIN-EQ",  # too many segments
    ],
)
def test_invalid_symbols_rejected(sym):
    assert symbols.validate_symbol(sym) is False


def test_index_constants_are_valid_symbols():
    for const in (symbols.NIFTY_50, symbols.BANK_NIFTY, symbols.FIN_NIFTY):
        assert symbols.validate_symbol(const), f"{const} is not a valid Fyers symbol"


def test_default_index_is_nifty50():
    assert symbols.DEFAULT_INDEX == symbols.NIFTY_50


# market_utils.py


@freeze_time("2026-08-03 06:00:00")  # 11:30 IST, a Monday
def test_market_hours_true_during_the_session():
    assert market_utils.is_market_hours() is True


@freeze_time("2026-08-03 02:00:00")  # 07:30 IST, before the open
def test_market_hours_false_before_open():
    assert market_utils.is_market_hours() is False


@freeze_time("2026-08-03 11:00:00")  # 16:30 IST, after the close
def test_market_hours_false_after_close():
    assert market_utils.is_market_hours() is False


@freeze_time("2026-08-08 06:00:00")  # Saturday, mid-session time
def test_market_hours_false_at_the_weekend():
    assert market_utils.is_market_hours() is False


@freeze_time("2026-08-03 03:45:00")  # exactly 09:15 IST
def test_market_open_boundary_is_inclusive():
    assert market_utils.is_market_hours() is True


# config.py — no secret may have a usable default

SECRET_KEYS = [
    "FYERS_CLIENT_ID",
    "FYERS_SECRET_ID",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]


@pytest.mark.parametrize("key", SECRET_KEYS)
def test_no_secret_has_a_hardcoded_value(key):
    """
    Every secret must come from the environment. A non-empty literal here would
    mean a credential is committed to the repository.
    """
    import inspect

    source = inspect.getsource(config)
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key} ="):
            assert "os.getenv" in stripped or "os.environ" in stripped, (
                f"{key} must be read from the environment, got: {stripped}"
            )


def test_no_secret_is_assigned_a_string_literal():
    """
    Asserts against the SOURCE, not the loaded values.

    Loading cannot be used here: config.py calls load_dotenv() at import time, so
    reloading the module re-reads .env from disk and repopulates every secret no
    matter what the environment says. Inspecting the AST is both correct and
    incapable of leaking a live credential into test output.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(config))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in SECRET_KEYS:
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    offenders.append(target.id)  # name only — never the value

    assert not offenders, (
        f"secret(s) assigned a hardcoded string literal in config.py: {offenders}. "
        f"Every secret must come from os.getenv()."
    )


def test_dotenv_file_is_git_ignored():
    """The secrets do come from a file; that file must never be committed."""
    import subprocess

    # Anchor on the repository root, not on config.py's directory — after the
    # src/ restructure those are no longer the same place.
    from shortcircuit import paths

    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            cwd=paths.PROJECT_ROOT,
            capture_output=True,
        )
    except FileNotFoundError:
        pytest.skip("git not available (e.g. inside the runtime container)")
    if result.returncode == 128:
        pytest.skip("not a git working tree (e.g. running from a source archive)")
    assert result.returncode == 0, ".env is not git-ignored"


# config.py — invariants the risk model depends on


def test_scanner_gain_band_is_ordered():
    assert config.SCANNER_GAIN_MIN_PCT < config.SCANNER_GAIN_MAX_PCT


def test_confidence_tiers_are_ordered():
    assert (
        config.STRATEGY_VWAP_SD_FLOOR
        <= config.STRATEGY_VWAP_SD_HIGH
        <= config.STRATEGY_VWAP_SD_EXTREME
    )


def test_leverage_is_positive():
    assert config.INTRADAY_LEVERAGE > 0


def test_max_session_loss_is_a_positive_magnitude():
    """Stored as a positive number and compared against a negative PnL."""
    assert config.MAX_SESSION_LOSS_INR > 0


def test_volume_fade_threshold_is_a_ratio_below_one():
    assert 0 < config.STRATEGY_VOL_FADE_MAX_RATIO < 1


def test_trade_direction_is_a_recognised_value():
    assert config.TRADE_DIRECTION in ("SHORT", "LONG")


def test_time_stop_disabled_or_positive():
    """0 disables the time-based exit; a negative value would be nonsensical."""
    assert config.MAX_HOLD_TIME_MINUTES >= 0


def test_minutes_since_market_open_is_zero_before_the_open():
    with freeze_time("2026-08-03 02:00:00"):  # 07:30 IST
        assert config.minutes_since_market_open() == 0.0


def test_minutes_since_market_open_counts_forward():
    with freeze_time("2026-08-03 04:15:00"):  # 09:45 IST, 30 min after open
        assert config.minutes_since_market_open() == pytest.approx(30.0, abs=1.0)
