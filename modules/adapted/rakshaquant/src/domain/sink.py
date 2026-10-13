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
Event sinks: how producers (market data, lifecycle, OMS, ...) emit events without knowing where
they go. A sink stamps the payload with its clock's time and records it.

* :class:`RecordingSink` keeps events in memory (tests, demo).
* ``src.store.sink.StoreSink`` appends them to the event store.
"""


from typing import Protocol, TypeVar

from src.domain.base import EventPayload
from src.domain.clock import Clock
from src.domain.events import Event, make_event

P = TypeVar("P", bound=EventPayload)


class EventSink(Protocol):
    def emit(
        self, payload: EventPayload, *, source: str | None = None, cycle_id: str | None = None
    ) -> Event:
        """Record ``payload`` now; return the stored event (with ``seq``)."""
        ...


class RecordingSink:
    def __init__(self, clock: Clock, source: str = "test") -> None:
        self._clock = clock
        self._source = source
        self.events: list[Event] = []

    def emit(
        self, payload: EventPayload, *, source: str | None = None, cycle_id: str | None = None
    ) -> Event:
        event = make_event(
            payload, ts=self._clock.now(), source=source or self._source, cycle_id=cycle_id
        ).with_seq(len(self.events) + 1)
        self.events.append(event)
        return event

    def payloads(self, kind: type[P]) -> list[P]:
        return [e.payload for e in self.events if isinstance(e.payload, kind)]
