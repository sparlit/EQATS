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


"""Race-free lazy singletons that real threads and request threads can share.

The pattern it replaces is everywhere:

    _client = None

    def get_client():
        global _client
        if _client is None:
            _client = build_client()
        return _client

Two threads arriving together both see None and both build, and the loser's
object is orphaned with whatever it holds: a connection pool, an executor's
threads, a websocket. Under eventlet the check and the assignment could not
interleave; under the gthread worker they can.

:class:`LazyInit` is double-checked: the fast path is one attribute read, and
only a caller that finds nothing takes the lock and checks again.

**The factory must only construct.** It runs under a real lock (from
``utils.real_threading``), because the agent, Telegram and websocket-loop
threads are real OS threads and reach these singletons too. Under eventlet a
greenlet that yields while holding a real lock, and a second greenlet that then
waits on it, freeze the whole worker. So a factory builds objects and returns;
it must not connect, authenticate or wait on the network. Do that work on first
use, outside the lock.
"""


from collections.abc import Callable

from utils import real_threading

_UNSET = object()


class LazyInit[T]:
    """A value built once, on first use, by exactly one caller.

    Args:
        factory: Builds the value. Construction only; see the module docstring.
        name: A label for logs and diagnostics.
    """

    def __init__(self, factory: Callable[[], T], name: str):
        self._factory = factory
        self.name = name
        self._lock = real_threading.Lock()
        self._value: object = _UNSET

    def get(self) -> T:
        """Return the value, building it if this is the first call.

        If the factory raises, nothing is stored and the next call tries again.
        """
        value = self._value
        if value is not _UNSET:
            return value  # type: ignore[return-value]
        with self._lock:
            if self._value is _UNSET:
                self._value = self._factory()
            return self._value  # type: ignore[return-value]

    def peek(self) -> T | None:
        """Return the value if it has been built, else None. Never builds."""
        value = self._value
        return None if value is _UNSET else value  # type: ignore[return-value]

    def reset(self, close: Callable[[T], None] | None = None) -> None:
        """Forget the value so the next get() builds a fresh one.

        Args:
            close: Optional; called with the old value, under the same lock, so
                no caller can be handed the object while it is being closed.
                Like the factory it must not wait on the network.
        """
        with self._lock:
            value, self._value = self._value, _UNSET
            if close is not None and value is not _UNSET:
                close(value)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        state = "unset" if self._value is _UNSET else "set"
        return f"LazyInit({self.name!r}, {state})"


__all__ = ["LazyInit"]
