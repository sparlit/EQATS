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


"""Abstract base class for browser automation clients."""


import abc
from typing import Any


class BaseBrowserClient(abc.ABC):
    """Abstract interface for browser automation tools."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Launch the browser."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Close the browser."""

    @abc.abstractmethod
    async def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        """Navigate to a URL.

        Args:
            url: Target URL
            wait_until: "load", "domcontentloaded", or "networkidle"
        """

    @abc.abstractmethod
    async def get_content(self) -> str:
        """Get page HTML content."""

    @abc.abstractmethod
    async def get_text(self, selector: str | None = None) -> str:
        """Get text content of page or element.

        Args:
            selector: CSS selector. None = entire page.
        """

    @abc.abstractmethod
    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        """Query all matching elements.

        Returns list of dicts with keys: text, html, attributes, inner_text.
        """

    @abc.abstractmethod
    async def evaluate(self, js: str) -> Any:
        """Execute JavaScript in the page context."""

    @abc.abstractmethod
    async def screenshot(self, path: str | None = None) -> bytes | None:
        """Take a screenshot. Returns PNG bytes if path is None."""

    @abc.abstractmethod
    async def intercept_requests(self, pattern: str = "*") -> list[dict]:
        """Intercept network requests matching pattern.

        Returns list of dicts with: url, method, headers, body.
        """

    @abc.abstractmethod
    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> bool:
        """Wait for an element to appear.

        Returns True if found, False if timed out.
        """

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
