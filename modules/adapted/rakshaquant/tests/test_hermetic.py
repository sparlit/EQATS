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


"""Guards for the hermetic harness in conftest.py (plan M0.3)."""

import os
from pathlib import Path

from src.config.settings import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cwd_is_isolated_from_repo(tmp_path):
    assert Path.cwd() == tmp_path
    assert Path.cwd().resolve() != REPO_ROOT


def test_env_file_is_never_read():
    assert Settings.model_config.get("env_file") is None


def test_settings_carry_no_real_credentials():
    s = get_settings()
    assert s.groq_api_key.get_secret_value() == "test-groq-key"
    assert s.dhan_client_id is None
    assert s.dhan_access_token is None
    assert not any(k.startswith(("DHAN_", "TELEGRAM_")) for k in os.environ)


# A name the scrubber ignores, so part 2 proves os.environ is restored (runs in file order).
_PROBE = "RQ_HERMETIC_LEAK_PROBE"


def test_environ_writes_do_not_leak_part1():
    os.environ[_PROBE] = "leak"


def test_environ_writes_do_not_leak_part2():
    assert _PROBE not in os.environ
