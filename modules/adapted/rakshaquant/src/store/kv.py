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
Durable key/value state for components that keep their own state outside the event log (the
simulated broker's exchange-side book, the exit manager's stops). Not a projection.
"""


from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from src.store.event_store import EventStore


class StateStore(Protocol):
    def load(self) -> str | None: ...

    def save(self, value: str, ts: datetime) -> None: ...


class MemoryStateStore:
    def __init__(self) -> None:
        self.value: str | None = None

    def load(self) -> str | None:
        return self.value

    def save(self, value: str, ts: datetime) -> None:
        self.value = value


class KVStateStore:
    """Keeps one component's state in the event store's ``kv_state`` table."""

    def __init__(self, store: EventStore, key: str, namespace: str) -> None:
        self._store, self._namespace, self._key = store, namespace, key

    def load(self) -> str | None:
        return self._store.kv_get(self._namespace, self._key)

    def save(self, value: str, ts: datetime) -> None:
        self._store.kv_put(self._namespace, self._key, value, ts)


class RecordStore(Protocol):
    """Row-wise durable state: only the rows that changed are written (O(changes), not O(N))."""

    def load_all(self) -> dict[str, str]: ...

    def put_many(self, rows: Mapping[str, str], ts: datetime) -> None: ...


class MemoryRecordStore:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def load_all(self) -> dict[str, str]:
        return dict(self.rows)

    def put_many(self, rows: Mapping[str, str], ts: datetime) -> None:
        self.rows.update(rows)


class KVRecordStore:
    """One component's rows in the event store's ``kv_state`` table, under one namespace."""

    def __init__(self, store: EventStore, namespace: str) -> None:
        self._store, self._namespace = store, namespace

    def load_all(self) -> dict[str, str]:
        return self._store.kv_items(self._namespace)

    def put_many(self, rows: Mapping[str, str], ts: datetime) -> None:
        self._store.kv_put_many(self._namespace, rows, ts)
