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


"""Persistent, crash-safe tracking for delivery reports published late."""


from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any

from .state_store import VersionedJSONStore

#: A delivery report is published the same evening as the trading session.
#: One that has still not appeared after this long does not exist -- the date
#: is not late, it is absent -- and retrying it forever is what kept a
#: historical backfill reporting errors on every run.
MAX_PENDING_DELIVERY_DAYS = 30

#: A second bound for someone who runs the application many times a day, where
#: the age rule would take a month to fire.  Twenty requests for the same URL
#: is enough evidence on its own.
MAX_DELIVERY_ATTEMPTS = 20


class PendingDeliveryStore:
    """Store pending exchange/segment dates in the application's data folder.

    Each pending date carries when it was first queued and how many times it
    has been attempted, because the store's job is not only to remember a late
    report but to eventually stop asking for one that will never arrive.
    """

    _lock = Lock()

    def __init__(self, base_data_path: Path):
        self.state_dir = Path(base_data_path) / ".state"
        self.path = self.state_dir / "pending_delivery.json"
        self._state = VersionedJSONStore(
            self.path,
            default={"version": 2, "pending": {}},
            validator=self._validate,
            quarantine_root=self.state_dir / "quarantine",
            category="pending_delivery",
            migrate=self._migrate,
        )

    @staticmethod
    def _migrate(data: dict) -> dict:
        """Upgrade the version 1 shape, which held bare date lists.

        A version 1 entry has no record of when it was queued, and the honest
        substitute is the trading date itself: an entry carried over from an
        older build is at least that old, so it retires on the first run rather
        than getting a fresh 30-day lease.
        """

        if data.get("version") != 1:
            return data
        pending = data.get("pending")
        if not isinstance(pending, dict):
            return data
        upgraded: dict[str, Any] = {}
        for key, values in pending.items():
            if not isinstance(values, list):
                return data
            entries: dict[str, Any] = {}
            for value in values:
                if not isinstance(value, str):
                    return data
                entries[value] = {"first_seen": value, "attempts": 1}
            upgraded[key] = entries
        return {"version": 2, "pending": upgraded}

    @staticmethod
    def _validate(data: dict) -> None:
        if data.get("version") != 2:
            raise ValueError("unsupported pending-delivery state version")
        pending = data.get("pending")
        if not isinstance(pending, dict):
            raise ValueError("pending-delivery state must contain an object")
        for key, entries in pending.items():
            if not isinstance(key, str) or not isinstance(entries, dict):
                raise ValueError("invalid pending-delivery entry")
            for value, record in entries.items():
                if not isinstance(value, str):
                    raise ValueError("pending-delivery date must be text")
                date.fromisoformat(value)
                if not isinstance(record, dict):
                    raise ValueError("pending-delivery record must be an object")
                date.fromisoformat(str(record.get("first_seen")))
                attempts = record.get("attempts")
                if not isinstance(attempts, int) or attempts < 1:
                    raise ValueError("pending-delivery attempts are invalid")

    def _read(self) -> dict:
        return self._state.read()

    def _write(self, data: dict) -> None:
        self._state.write(data)

    @staticmethod
    def _key(exchange: str, segment: str) -> str:
        return f"{exchange.upper()}_{segment.upper()}"

    def add(
        self,
        exchange: str,
        segment: str,
        target_date: date,
        *,
        today: date | None = None,
    ) -> None:
        """Queue a late delivery report, counting this attempt."""

        key = self._key(exchange, segment)
        value = target_date.isoformat()
        with self._lock:
            data = self._read()
            entries = data["pending"].setdefault(key, {})
            record = entries.get(value)
            if isinstance(record, dict):
                record["attempts"] = int(record.get("attempts", 1)) + 1
            else:
                entries[value] = {
                    "first_seen": (today or target_date).isoformat(),
                    "attempts": 1,
                }
            self._write(data)

    def discard(self, exchange: str, segment: str, target_date: date) -> None:
        key = self._key(exchange, segment)
        value = target_date.isoformat()
        with self._lock:
            data = self._read()
            entries = data["pending"].get(key)
            if not isinstance(entries, dict):
                return
            entries.pop(value, None)
            if not entries:
                data["pending"].pop(key, None)
            self._write(data)

    def dates(self, exchange: str, segment: str) -> list[date]:
        key = self._key(exchange, segment)
        with self._lock:
            entries = self._read()["pending"].get(key, {})
        result = []
        for raw_date in entries:
            try:
                result.append(date.fromisoformat(raw_date))
            except (TypeError, ValueError):
                continue
        return sorted(set(result))

    def attempts(self, exchange: str, segment: str, target_date: date) -> int:
        """How many times this date's delivery report has been requested."""

        key = self._key(exchange, segment)
        with self._lock:
            entries = self._read()["pending"].get(key, {})
        record = entries.get(target_date.isoformat())
        return int(record.get("attempts", 0)) if isinstance(record, dict) else 0

    def expire(
        self,
        exchange: str,
        segment: str,
        *,
        today: date,
        first_available: date | None = None,
    ) -> list[tuple[date, str]]:
        """Drop and return the dates whose report is absent rather than late.

        The caller is responsible for retiring the pipeline stage for each
        returned date; removing the entry here only stops it being re-queued.
        """

        key = self._key(exchange, segment)
        retired: list[tuple[date, str]] = []
        with self._lock:
            data = self._read()
            entries = data["pending"].get(key)
            if not isinstance(entries, dict) or not entries:
                return retired
            for value in sorted(entries):
                try:
                    target_date = date.fromisoformat(value)
                except (TypeError, ValueError):
                    retired.append((today, "unreadable pending entry"))
                    entries.pop(value, None)
                    continue
                reason = self._expiry_reason(entries[value], target_date, today, first_available)
                if reason is None:
                    continue
                retired.append((target_date, reason))
                entries.pop(value, None)
            if not entries:
                data["pending"].pop(key, None)
            if retired:
                self._write(data)
        return retired

    @staticmethod
    def _expiry_reason(
        record: Any,
        target_date: date,
        today: date,
        first_available: date | None,
    ) -> str | None:
        if first_available is not None and target_date < first_available:
            return f"The exchange published no delivery report before {first_available.isoformat()}"
        first_seen = target_date
        if isinstance(record, dict):
            try:
                first_seen = date.fromisoformat(str(record.get("first_seen")))
            except (TypeError, ValueError):
                first_seen = target_date
        waited = (today - first_seen).days
        if waited >= MAX_PENDING_DELIVERY_DAYS:
            return f"No delivery report appeared in {MAX_PENDING_DELIVERY_DAYS} days"
        attempts = int(record.get("attempts", 1)) if isinstance(record, dict) else 1
        if attempts >= MAX_DELIVERY_ATTEMPTS:
            return f"No delivery report after {attempts} attempts"
        return None
