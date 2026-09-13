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


"""Composite-bar aggregation and indicator fan-out, shared by both runners.

A strategy declares timeframes with ``subscribe_bars`` and indicators with
``register_indicator``, both from ``on_start``. This module owns what those
declarations become at run time: one :class:`BarAggregator` per subscription
(per symbol, in portfolio runs) and an index from stream to the indicators
listening on it.

Ordering, in both runners: a completed composite bar dispatches *before* the
primary ``on_bar`` of the bar that completed it, because the composite closed
strictly earlier. In portfolio runs that guarantee is per symbol — a
symbol's composite bars are built only from its own bars, and cross-symbol
order follows the merged event schedule.
"""


try:
    from raptorbt._raptorbt import BarAggregator
    from raptorbt.strategy.context import CompositeBar
except ImportError:
    # Fallback for environments where raptorbt is not installed
    BarAggregator = object  # type: ignore
    CompositeBar = object  # type: ignore


def enumerate_subscriptions(subscriptions):
    """Yield ``(stream_id, (step, unit, brick_size))`` for each subscription.

    Subscriptions are stored as 2- or 3-tuples depending on whether a brick
    size was given.
    """
    for stream_id, sub in enumerate(subscriptions):
        step, unit = sub[0], sub[1]
        brick = sub[2] if len(sub) > 2 else 0.0
        yield stream_id, (step, unit, brick)


class StreamState:
    """Per-symbol aggregators and indicator routing for one run.

    ``symbols`` is the list of symbols in a portfolio run, or ``None`` for a
    single-instrument run (where registrations carry no symbol and every
    indicator sees the one stream).
    """

    def __init__(self, strategy, symbols: list[str] | None = None):
        subscriptions = list(strategy._bar_subscriptions)
        keys: list[str | None] = list(symbols) if symbols else [None]

        # (symbol, stream_id) -> aggregator. One per symbol per subscription,
        # so a symbol's composite bars are built from its bars alone.
        self._aggregators: dict[str | None, list[tuple[int, int, str, BarAggregator]]] = {
            key: [
                (stream_id, step, unit, BarAggregator(step, unit, brick_size=brick))
                for stream_id, (step, unit, brick) in enumerate_subscriptions(subscriptions)
            ]
            for key in keys
        }
