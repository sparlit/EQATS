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


"""An :class:`~src.domain.sink.EventSink` that appends to the event store."""


from src.domain.base import EventPayload
from src.domain.clock import Clock
from src.domain.events import Event, make_event
from src.store.event_store import EventStore


class StoreSink:
    def __init__(self, store: EventStore, clock: Clock, source: str) -> None:
        self._store = store
        self._clock = clock
        self._source = source

    def emit(
        self, payload: EventPayload, *, source: str | None = None, cycle_id: str | None = None
    ) -> Event:
        event = make_event(
            payload, ts=self._clock.now(), source=source or self._source, cycle_id=cycle_id
        )
        return event.with_seq(self._store.append(event))
