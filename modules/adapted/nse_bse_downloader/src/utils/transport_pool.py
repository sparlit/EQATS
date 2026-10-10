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


"""Run-scoped shared HTTP transport and conservative host policies."""


import asyncio
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import aiohttp

from ..core.exceptions import CircuitOpenError, NetworkError
from .tls import default_ssl_context


@dataclass
class HostPolicy:
    """Shared concurrency, spacing, and circuit state for one hostname."""

    limit: int
    interval: float
    semaphore: asyncio.Semaphore = field(init=False)
    clock_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    next_request_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0

    def __post_init__(self) -> None:
        self.semaphore = asyncio.Semaphore(max(1, self.limit))


class TransportPool:
    """One long-lived session with host-aware limits for a download run."""

    def __init__(self, config):
        settings = config.download_settings
        self.max_per_host = max(1, int(getattr(settings, "max_concurrent_downloads", 1)))
        self.rate_limit_delay = max(0.0, float(getattr(settings, "rate_limit_delay", 0.0)))
        self.circuit_threshold = 3
        self.circuit_cooldown = 30.0
        self.session: aiohttp.ClientSession | None = None
        self.policies: dict[str, HostPolicy] = {}

    async def __aenter__(self) -> TransportPool:
        await self.start()
        return self

    async def __aexit__(self, _exc_type, _exc, _traceback) -> None:
        await self.close()

    async def start(self) -> None:
        if self.session is not None:
            return
        timeout = aiohttp.ClientTimeout(total=None)
        connector = aiohttp.TCPConnector(
            limit=max(2, self.max_per_host * 2),
            limit_per_host=self.max_per_host,
            ttl_dns_cache=300,
            use_dns_cache=True,
            keepalive_timeout=60,
            enable_cleanup_closed=sys.version_info < (3, 13),
            force_close=False,
            ssl=default_ssl_context(),
        )
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,image/apng,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Cache-Control": "max-age=0",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
            connector=connector,
        )

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    def _policy(self, url: str) -> HostPolicy:
        host = (urlsplit(url).hostname or "").lower()
        if not host:
            raise NetworkError("Download URL has no hostname", url=url)
        if host not in self.policies:
            self.policies[host] = HostPolicy(self.max_per_host, self.rate_limit_delay)
        return self.policies[host]

    @asynccontextmanager
    async def slot(self, url: str) -> AsyncIterator[HostPolicy]:
        policy = self._policy(url)
        now = time.monotonic()
        if policy.circuit_open_until > now:
            raise CircuitOpenError(f"Host circuit open for {urlsplit(url).hostname}", url=url)
        async with policy.semaphore:
            async with policy.clock_lock:
                wait = max(0.0, policy.next_request_at - time.monotonic())
                policy.next_request_at = (
                    max(policy.next_request_at, time.monotonic()) + policy.interval
                )
            if wait:
                await asyncio.sleep(wait)
            yield policy

    def record(self, url: str, *, success: bool, status_code: int | None = None) -> None:
        policy = self._policy(url)
        transient = not success and (
            status_code is None or status_code in {403, 408, 425, 429} or status_code >= 500
        )
        if success:
            policy.consecutive_failures = 0
            policy.circuit_open_until = 0.0
        elif transient:
            policy.consecutive_failures += 1
            if policy.consecutive_failures >= self.circuit_threshold:
                policy.circuit_open_until = time.monotonic() + self.circuit_cooldown
