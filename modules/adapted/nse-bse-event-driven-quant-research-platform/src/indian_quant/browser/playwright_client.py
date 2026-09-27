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


"""Playwright browser client — primary tool for web scraping.

Best for: Standard websites, SPAs, form automation.
Anti-detection: Good (can add stealth plugins).
"""


import logging
from typing import Any

from indian_quant.browser.base import BaseBrowserClient

log = logging.getLogger(__name__)


class PlaywrightBrowserClient(BaseBrowserClient):
    """Playwright-based browser client."""

    def __init__(self, headless: bool = True, proxy: dict | None = None):
        self.headless = headless
        self.proxy = proxy
        self._playwright = None
        self._browser = None
        self._page = None
        self._context = None
        self._intercepted: list[dict] = []

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_args = {"headless": self.headless}
        if self.proxy:
            launch_args["proxy"] = self.proxy

        self._browser = await self._playwright.chromium.launch(**launch_args)
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()

        # Enable request interception
        self._page.on("response", self._on_response)
        log.info("Playwright browser started")

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        log.info("Playwright browser stopped")

    def _on_response(self, response):
        """Capture intercepted responses."""
        self._intercepted.append(
            {
                "url": response.url,
                "status": response.status,
                "headers": dict(response.headers),
            }
        )

    async def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        self._intercepted.clear()
        await self._page.goto(url, wait_until=wait_until)
        log.debug("Navigated to %s", url)

    async def get_content(self) -> str:
        return await self._page.content()

    async def get_text(self, selector: str | None = None) -> str:
        if selector:
            el = await self._page.query_selector(selector)
            return await el.inner_text() if el else ""
        return await self._page.inner_text("body")

    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        elements = await self._page.query_selector_all(selector)
        results = []
        for el in elements:
            results.append(
                {
                    "text": await el.inner_text(),
                    "html": await el.inner_html(),
                    "attributes": await el.evaluate(
                        "el => Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))"
                    ),
                    "inner_text": await el.inner_text(),
                }
            )
        return results

    async def evaluate(self, js: str) -> Any:
        return await self._page.evaluate(js)

    async def screenshot(self, path: str | None = None) -> bytes | None:
        if path:
            await self._page.screenshot(path=path)
            return None
        return await self._page.screenshot()

    async def intercept_requests(self, pattern: str = "*") -> list[dict]:
        return [r for r in self._intercepted if pattern == "*" or pattern in r["url"]]

    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> bool:
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def fill(self, selector: str, text: str) -> None:
        await self._page.fill(selector, text)

    async def click(self, selector: str) -> None:
        await self._page.click(selector)
