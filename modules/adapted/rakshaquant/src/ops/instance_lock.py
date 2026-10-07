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
Single-instance guard: at most one RakshaQuant process per state directory.

Two processes on the same ``state_dir`` (say, the CLI and the web console) would overwrite
each other's state. The guard is an OS-level lock on ``<state_dir>/rakshaquant.lock``, so it
is released automatically if the holder crashes. Different environments use different state
directories and so never block each other.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

LOCK_FILE_NAME = "rakshaquant.lock"


class InstanceLockHeldError(RuntimeError):
    """Another process already holds the lock for this state directory."""


@contextmanager
def single_instance(state_dir: Path) -> Iterator[Path]:
    """Hold the state directory's lock for the duration of the block.

    Raises :class:`InstanceLockHeldError` at once, without waiting, if another holder exists.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / LOCK_FILE_NAME
    lock = FileLock(lock_path, blocking=False)
    try:
        lock.acquire()
    except Timeout:
        raise InstanceLockHeldError(
            f"Another RakshaQuant instance is already running on {state_dir} "
            f"(lock file {lock_path}). Stop it first, or use a different ENVIRONMENT."
        ) from None
    try:
        yield lock_path
    finally:
        lock.release()
