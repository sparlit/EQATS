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


"""Obscura browser client — lightweight fallback.

Best for: High-volume scraping, memory-constrained environments.
Anti-detection: Excellent (fingerprint randomization).
Requires: obscura binary installed.
"""


import asyncio
import json
import logging
import subprocess
from typing import Any

from indian_quant.browser.base import BaseBrowserClient

log = logging.getLogger(__name__)

OBSCURA_PORT = 9222


class ObscuraBrowserClient(BaseBrowserClient):
    """Obscura-based browser client via CLI or CDP.

    Uses Obscura CLI for quick fetches, or CDP for complex interactions.
    """

    def __init__(self, headless: bool = True, proxy: dict | None = None):
        self.headless = headless
        self.proxy = proxy
        self._server_process: subprocess.Popen | None = None

    async def start(self) -> None:
        # Check if obscura is installed
        try:
            result = subprocess.run(["obscura", "--version"], capture_output=True, timeout=5)
            if result.returncode != 0:
                raise FileNotFoundError("obscura not found")
        except FileNotFoundError:
            raise RuntimeError(
                "Obscura not installed. Install from: "
                "https://github.com/h4ckf0r0day/obscura/releases"
            )

        # Launch CDP server for complex interactions
        cmd = ["obscura", "serve", "--port", str(OBSCURA_PORT)]
        if self.proxy:
            cmd.extend(["--proxy", self.proxy.get("server", "")])
        if self.headless:
            cmd.append("--stealth")

        self._server_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        await asyncio.sleep(2)  # Wait for server to start
        log.info("Obscura CDP server started on port %d", OBSCURA_PORT)

    async def stop(self) -> None:
        if self._server_process:
            self._server_process.terminate()
            self._server_process.wait(timeout=5)
        log.info("Obscura client stopped")

    async def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        """Navigate using CDP via Playwright."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"ws://127.0.0.1:{OBSCURA_PORT}")
            context = browser.contexts[0]
            page = await context.new_page()
            await page.goto(url, wait_until=wait_until)
            await browser.close()

    async def get_content(self) -> str:
        """Quick fetch using CLI."""
        result = subprocess.run(
            ["obscura", "fetch", "--eval", "document.documentElement.outerHTML"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    async def get_text(self, selector: str | None = None) -> str:
        if selector:
            js = f'document.querySelector("{selector}")?.innerText || ""'
        else:
            js = "document.body.innerText"
        result = subprocess.run(
            ["obscura", "fetch", "--eval", js], capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()

    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        js = f"""
        JSON.stringify(Array.from(document.querySelectorAll('{selector}')).map(el => ({{
            text: el.innerText,
            html: el.innerHTML,
            innerText: el.innerText,
            attributes: Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))
        }})))
        """
        result = subprocess.run(
            ["obscura", "fetch", "--eval", js], capture_output=True, text=True, timeout=30
        )
        try:
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            return []

    async def evaluate(self, js: str) -> Any:
        result = subprocess.run(
            ["obscura", "fetch", "--eval", js], capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()

    async def screenshot(self, path: str | None = None) -> bytes | None:
        if path:
            subprocess.run(
                ["obscura", "fetch", "--screenshot", path], capture_output=True, timeout=30
            )
            return None
        result = subprocess.run(
            ["obscura", "fetch", "--screenshot", "/dev/stdout"], capture_output=True, timeout=30
        )
        return result.stdout

    async def intercept_requests(self, pattern: str = "*") -> list[dict]:
        return []

    async def wait_for_selector(self, selector: str, timeout: int = 30000) -> bool:
        js = f"""
        new Promise((resolve) => {{
            const check = () => {{
                if (document.querySelector('{selector}')) resolve(true);
                else setTimeout(check, 100);
            }};
            check();
            setTimeout(() => resolve(false), {timeout});
        }})
        """
        result = await self.evaluate(js)
        return result == "true"
