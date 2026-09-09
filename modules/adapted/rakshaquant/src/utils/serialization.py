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
Serialization helpers.

The LangGraph pipeline checkpoints ``TradingState`` through msgpack (``MemorySaver`` uses
``JsonPlusSerializer``). msgpack's type check is *exact*: a ``numpy.float64`` (even though it
subclasses ``float``) or a ``numpy.int64`` reaching that boundary raises
``TypeError: Type is not msgpack serializable: numpy.float64`` and crashes the whole cycle.

Values computed with pandas / scikit-learn (the ML prediction agent, P&L derived from
quote prices, drawdown, etc.) are numpy scalars unless explicitly coerced. ``to_native``
walks a nested structure and converts every numpy scalar/array to the equivalent native
Python type so the state is always msgpack-safe.
"""


from typing import Any

import numpy as np


def to_native(obj: Any) -> Any:
    """
    Recursively convert numpy scalars/arrays inside ``obj`` to native Python types.

    - numpy scalar (``np.generic``, e.g. ``float64``/``int64``/``bool_``) -> ``.item()``
    - numpy array -> ``list`` (recursively native, via ``tolist``)
    - dict / list / tuple -> same container with each element converted
    - everything else is returned unchanged

    Safe to call on already-native data (it is a no-op for plain Python values).
    """
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return to_native(obj.tolist())
    if isinstance(obj, dict):
        return {key: to_native(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_native(item) for item in obj]
    return obj
