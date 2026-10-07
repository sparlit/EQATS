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
Lineage context for logs (plan M1.6; audit §O.1): ``cycle_id``, ``decision_id``, ``component``,
``symbol`` and ``book_id`` live in ``contextvars``, so every log record emitted inside a
:func:`log_context` block carries them. ``asyncio`` tasks and ``asyncio.to_thread`` copy the
current context, so the ids follow work into tasks and worker threads.
"""


from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

CONTEXT_FIELDS = ("cycle_id", "decision_id", "component", "symbol", "book_id")

_VARS: dict[str, ContextVar[str | None]] = {
    name: ContextVar(f"rq_{name}", default=None) for name in CONTEXT_FIELDS
}


@contextmanager
def log_context(**values: str | None) -> Iterator[None]:
    """Set lineage fields for the duration of the block (nested blocks override, then restore)."""
    unknown = set(values) - set(CONTEXT_FIELDS)
    if unknown:
        raise TypeError(f"unknown log context fields: {sorted(unknown)}")
    tokens: list[tuple[ContextVar[str | None], Token[str | None]]] = [
        (_VARS[name], _VARS[name].set(value)) for name, value in values.items()
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current_context() -> dict[str, str | None]:
    return {name: var.get() for name, var in _VARS.items()}
