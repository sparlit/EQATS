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


# rest_limiter.py
"""
Global REST rate limiter for Fyers API v3.

Fyers enforces THREE simultaneous limits per User ID, shared across every endpoint:

    10 requests / second
    200 requests / minute
    100,000 requests / day

The previous implementation enforced only a per-second bucket at 8 rps. Sustained,
that is 480 requests/minute — 2.4x over the per-minute cap — which is why session logs
accumulated hundreds of rate-limit responses. All three windows must hold at once.

Two further properties matter for a live trading system:

  * Priority. A stop-loss placement must never queue behind 300 scanner quote calls.
    HIGH-priority callers draw on a reserved slice of each window that NORMAL callers
    cannot touch, and NORMAL callers stand down while a HIGH caller is waiting.

  * Observability. Waits and rejections are counted, so /health can distinguish
    "the broker is throttling us" from "our own limiter is shaping us".

Usage:
    from shortcircuit.broker.rest_limiter import rest_limiter, Priority

    rest_limiter.acquire()                                   # scanner / background
    rest_limiter.acquire(priority=Priority.HIGH)             # orders, SL, exits
    await rest_limiter.acquire_async(priority=Priority.HIGH)  # from async code
"""


import asyncio
import logging
import threading
import time
from collections import deque
from enum import IntEnum

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Higher wins. HIGH is reserved for the order path."""

    NORMAL = 0
    HIGH = 1


class RateLimiter:
    """
    Thread-safe multi-window limiter with priority reservation.

    Each window is a sliding log of grant timestamps rather than a fixed-window
    counter, so a burst at t=0.9s cannot double-spend into the next wall-clock
    second — the classic flaw that still trips the broker's own counter.
    """

    def __init__(
        self,
        per_second: int = 9,
        per_minute: int = 190,
        per_day: int = 95_000,
        reserve_second: int = 3,
        reserve_minute: int = 40,
    ):
        # Ceilings sit deliberately under the documented broker limits, so clock skew
        # and in-flight SDK retries cannot push the real count over.
        self._per_second = per_second
        self._per_minute = per_minute
        self._per_day = per_day

        # What NORMAL callers may consume; the remainder is HIGH-only headroom.
        self._normal_second = max(1, per_second - reserve_second)
        self._normal_minute = max(1, per_minute - reserve_minute)

        self._sec_log: deque[float] = deque()
        self._min_log: deque[float] = deque()

        self._day_count = 0
        self._day_epoch = self._today_epoch()

        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._waiting_high = 0

        # Telemetry
        self.total_granted = 0
        self.total_wait_seconds = 0.0
        self.total_day_rejections = 0
        self.max_wait_seconds = 0.0

    # internals (lock must be held)

    @staticmethod
    def _today_epoch() -> float:
        """Local start-of-day; the daily quota resets on the broker's calendar day."""
        lt = time.localtime()
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))

    def _evict(self, now: float) -> None:
        sec_cutoff = now - 1.0
        while self._sec_log and self._sec_log[0] <= sec_cutoff:
            self._sec_log.popleft()

        min_cutoff = now - 60.0
        while self._min_log and self._min_log[0] <= min_cutoff:
            self._min_log.popleft()

        if now - self._day_epoch >= 86_400:
            self._day_epoch = self._today_epoch()
            self._day_count = 0
            logger.info("[RATE] Daily request counter reset.")

    def _capacity(self, priority: int) -> tuple[int, int]:
        if priority >= Priority.HIGH:
            return self._per_second, self._per_minute
        return self._normal_second, self._normal_minute

    def _retry_after(self, now: float, priority: int) -> float:
        """Seconds until the binding window frees a slot."""
        sec_cap, min_cap = self._capacity(priority)
        waits = []
        if len(self._sec_log) >= sec_cap:
            waits.append(self._sec_log[0] + 1.0 - now)
        if len(self._min_log) >= min_cap:
            waits.append(self._min_log[0] + 60.0 - now)
        if not waits:
            return 0.0
        return max(0.001, min(max(waits), 60.0))

    # public API

    def acquire(
        self,
        priority: int = Priority.NORMAL,
        timeout: float | None = None,
    ) -> bool:
        """
        Block until a request slot is free, then consume it.

        Returns True when granted, False if `timeout` elapsed or the daily quota is
        exhausted. Existing no-arg callers keep their old blocking semantics.
        """
        started = time.monotonic()
        deadline = None if timeout is None else started + timeout
        is_high = priority >= Priority.HIGH

        with self._cv:
            if is_high:
                self._waiting_high += 1
            try:
                while True:
                    now = time.time()
                    self._evict(now)

                    if self._day_count >= self._per_day:
                        self.total_day_rejections += 1
                        logger.critical(
                            "[RATE] Daily quota exhausted (%d). Refusing request.",
                            self._per_day,
                        )
                        return False

                    sec_cap, min_cap = self._capacity(priority)
                    has_room = len(self._sec_log) < sec_cap and len(self._min_log) < min_cap

                    # NORMAL stands down while HIGH is queued, so an order never sits
                    # behind scanner traffic that happened to arrive microseconds earlier.
                    blocked_by_priority = (not is_high) and self._waiting_high > 0

                    if has_room and not blocked_by_priority:
                        self._sec_log.append(now)
                        self._min_log.append(now)
                        self._day_count += 1
                        self.total_granted += 1

                        waited = time.monotonic() - started
                        if waited > 0:
                            self.total_wait_seconds += waited
                            self.max_wait_seconds = max(self.max_wait_seconds, waited)
                        return True

                    wait_for = self._retry_after(now, priority)
                    if blocked_by_priority:
                        wait_for = min(wait_for if wait_for > 0 else 0.05, 0.05)

                    if deadline is not None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            return False
                        wait_for = min(wait_for, remaining)

                    # Condition wait, not sleep: a releasing thread can wake us early.
                    self._cv.wait(timeout=wait_for)
            finally:
                if is_high:
                    self._waiting_high -= 1
                self._cv.notify_all()

    async def acquire_async(
        self,
        priority: int = Priority.NORMAL,
        timeout: float | None = None,
    ) -> bool:
        """Async wrapper — offloads the blocking wait so the event loop keeps running."""
        return await asyncio.to_thread(self.acquire, priority, timeout)

    def snapshot(self) -> dict:
        """Current utilisation, for /health and diagnostics."""
        with self._lock:
            now = time.time()
            self._evict(now)
            return {
                "used_second": len(self._sec_log),
                "cap_second": self._per_second,
                "used_minute": len(self._min_log),
                "cap_minute": self._per_minute,
                "used_day": self._day_count,
                "cap_day": self._per_day,
                "granted_total": self.total_granted,
                "wait_total_s": round(self.total_wait_seconds, 2),
                "wait_max_s": round(self.max_wait_seconds, 3),
                "day_rejections": self.total_day_rejections,
            }


# Singleton — import this everywhere.
rest_limiter = RateLimiter()

# Legacy alias: older code referenced the class by its former name.
TokenBucketRateLimiter = RateLimiter
