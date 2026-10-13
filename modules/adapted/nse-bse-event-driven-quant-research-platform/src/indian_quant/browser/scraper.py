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


"""Unified browser scraper with tool selection and fallback chains.

Tool selection by site:
  investorfeed.in → Playwright (no Cloudflare, simple SPA)
  concall.in      → Camofox (Cloudflare protected)
  screener.in     → Playwright + stealth
  default         → Playwright → Camofox → Obscura
"""


import logging
from typing import Any

from indian_quant.browser.base import BaseBrowserClient

log = logging.getLogger(__name__)

# Tool preference per site
SITE_TOOLS: dict[str, str] = {
    "investorfeed.in": "playwright",
    "concall.in": "camofox",
    "screener.in": "playwright",
    "trendlyne.com": "playwright",
    "chartink.com": "playwright",
    "bseindia.com": "playwright",
    "nseindia.com": "playwright",
}

# Fallback chain for each primary tool
FALLBACK_CHAINS: dict[str, list[str]] = {
    "playwright": ["playwright", "camofox", "obscura"],
    "camofox": ["camofox", "playwright", "obscura"],
    "obscura": ["obscura", "playwright", "camofox"],
}


def _get_tool_for_site(url: str) -> str:
    """Determine the best tool for a given URL."""
    for domain, tool in SITE_TOOLS.items():
        if domain in url:
            return tool
    return "playwright"


def _create_client(
    tool: str, headless: bool = True, proxy: dict | None = None
) -> BaseBrowserClient:
    """Create a browser client for the given tool."""
    if tool == "playwright":
        from indian_quant.browser.playwright_client import PlaywrightBrowserClient

        return PlaywrightBrowserClient(headless=headless, proxy=proxy)
    elif tool == "camofox":
        from indian_quant.browser.camofox_client import CamofoxBrowserClient

        return CamofoxBrowserClient(headless=headless, proxy=proxy)
    elif tool == "obscura":
        from indian_quant.browser.obscura_client import ObscuraBrowserClient

        return ObscuraBrowserClient(headless=headless, proxy=proxy)
    else:
        raise ValueError(f"Unknown tool: {tool}")


class BrowserScraper:
    """Unified browser scraper with automatic tool selection and fallback.

    Usage:
        async with BrowserScraper() as scraper:
            data = await scraper.scrape("https://investorfeed.in/company/reliance")
            text = await scraper.get_text("h1.company-name")
            elements = await scraper.query_selector_all(".data-row")
    """

    def __init__(
        self,
        tool: str | None = None,
        headless: bool = True,
        proxy: dict | None = None,
        max_retries: int = 2,
    ):
        self.preferred_tool = tool
        self.headless = headless
        self.proxy = proxy
        self.max_retries = max_retries
        self._client: BaseBrowserClient | None = None
        self._active_tool: str | None = None

    async def start(self, url: str | None = None) -> None:
        """Start browser, selecting best tool for the URL."""
        tool = self.preferred_tool or (_get_tool_for_site(url) if url else "playwright")
        await self._try_start(tool)

    async def _try_start(self, tool: str) -> bool:
        """Try to start a specific tool. Returns True on success."""
        try:
            self._client = _create_client(tool, self.headless, self.proxy)
            await self._client.start()
            self._active_tool = tool
            log.info("Started %s browser", tool)
            return True
        except Exception as e:
            log.warning("Failed to start %s: %s", tool, e)
            return False

    async def _fallback(self, failed_tool: str) -> bool:
        """Try fallback tools after a failure."""
        chain = FALLBACK_CHAINS.get(failed_tool, ["playwright", "camofox", "obscura"])
        for tool in chain:
            if tool == failed_tool:
                continue
            if await self._try_start(tool):
                return True
        return False

    async def stop(self) -> None:
        """Stop the active browser."""
        if self._client:
            try:
                await self._client.stop()
            except Exception as e:
                log.warning("Error stopping browser: %s", e)
        self._client = None
        self._active_tool = None

    async def scrape(self, url: str, wait_until: str = "networkidle") -> str:
        """Navigate to URL and return page content.

        Tries preferred tool first, falls back to alternatives on failure.
        """
        if not self._client:
            await self.start(url)

        for attempt in range(self.max_retries + 1):
            try:
                await self._client.navigate(url, wait_until)
                return await self._client.get_content()
            except Exception as e:
                log.warning(
                    "Scrape attempt %d failed with %s: %s", attempt + 1, self._active_tool, e
                )
                if attempt < self.max_retries:
                    if await self._fallback(self._active_tool):
                        continue
                raise

    async def get_text(self, selector: str | None = None) -> str:
        """Get text content from current page."""
        return await self._client.get_text(selector)

    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        """Query all matching elements."""
        return await self._client.query_selector_all(selector)

    async def evaluate(self, js: str) -> Any:
        """Execute JavaScript."""
        return await self._client.evaluate(js)

    async def screenshot(self, path: str | None = None) -> bytes | None:
        """Take screenshot."""
        return await self._client.screenshot(path)

    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> bool:
        """Wait for element to appear."""
        return await self._client.wait_for_selector(selector, timeout)

    @property
    def active_tool(self) -> str | None:
        """Currently active browser tool."""
        return self._active_tool

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
