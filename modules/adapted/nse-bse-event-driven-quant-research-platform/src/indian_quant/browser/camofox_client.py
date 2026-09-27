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


"""Camofox browser client — anti-detection fallback.

Best for: Cloudflare-protected sites, aggressive bot detection.
Anti-detection: Excellent (C++ fingerprint spoofing, Firefox-based).
Requires: camofox-browser npm package (Node.js).
"""


import asyncio
import contextlib
import json
import logging
import subprocess
from typing import Any

from indian_quant.browser.base import BaseBrowserClient

log = logging.getLogger(__name__)

CAMOFOX_PORT = 9377
CAMOFOX_URL = f"http://127.0.0.1:{CAMOFOX_PORT}"


class CamofoxBrowserClient(BaseBrowserClient):
    """Camofox-based browser client via REST API.

    Uses the Camofox Node.js server as a backend.
    Falls back to launching the server if not running.
    """

    def __init__(self, headless: bool = True, proxy: dict | None = None):
        self.headless = headless
        self.proxy = proxy
        self._tab_id: str | None = None
        self._server_process: subprocess.Popen | None = None
        self._started = False

    async def start(self) -> None:
        import httpx

        # Check if Camofox server is already running
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{CAMOFOX_URL}/health", timeout=2.0)
                if resp.status_code == 200:
                    self._started = True
                    log.info("Camofox server already running")
                    return
        except Exception:
            pass

        # Launch Camofox server
        log.info("Launching Camofox server on port %d", CAMOFOX_PORT)
        self._server_process = subprocess.Popen(
            ["npx", "camofox-browser", "serve", "--port", str(CAMOFOX_PORT)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Wait for server to start
        for _ in range(30):
            await asyncio.sleep(1)
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(f"{CAMOFOX_URL}/health", timeout=2.0)
                    if resp.status_code == 200:
                        self._started = True
                        log.info("Camofox server started")
                        return
            except Exception:
                continue
        msg = "Failed to start Camofox server"
        raise RuntimeError(msg)

    async def stop(self) -> None:
        if self._tab_id:
            await self._close_tab()
        if self._server_process:
            self._server_process.terminate()
            self._server_process.wait(timeout=5)
        log.info("Camofox client stopped")

    async def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        """Make a request to the Camofox REST API."""
        import httpx

        url = f"{CAMOFOX_URL}{path}"
        async with httpx.AsyncClient() as client:
            if method == "GET":
                resp = await client.get(url, timeout=30)
            elif method == "POST":
                resp = await client.post(url, json=data, timeout=30)
            elif method == "DELETE":
                resp = await client.delete(url, timeout=30)
            else:
                msg = f"Unknown method: {method}"
                raise ValueError(msg)
            return resp.json()

    async def navigate(self, url: str, wait_until: str = "networkidle") -> None:
        if not self._tab_id:
            tab = await self._request("POST", "/tabs", {"userId": "quant", "url": url})
            self._tab_id = tab.get("id")
        else:
            await self._request("POST", f"/tabs/{self._tab_id}/navigate", {"url": url})

    async def get_content(self) -> str:
        snapshot = await self._request("GET", f"/tabs/{self._tab_id}/snapshot")
        return snapshot.get("content", "")

    async def get_text(self, selector: str | None = None) -> str:
        if selector:
            return await self.evaluate(f'document.querySelector("{selector}")?.innerText || ""')
        snapshot = await self._request("GET", f"/tabs/{self._tab_id}/snapshot")
        return snapshot.get("text", "")

    async def query_selector_all(self, selector: str) -> list[dict[str, Any]]:
        js = f"""
        Array.from(document.querySelectorAll('{selector}')).map(el => ({{
            text: el.innerText,
            html: el.innerHTML,
            innerText: el.innerText,
            attributes: Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))
        }}))
        """
        result = await self.evaluate(js)
        return result if isinstance(result, list) else []

    async def evaluate(self, js: str) -> Any:
        result = await self._request("POST", f"/tabs/{self._tab_id}/eval", {"js": js})
        return result.get("result")

    async def screenshot(self, path: str | None = None) -> bytes | None:
        result = await self._request("GET", f"/tabs/{self._tab_id}/screenshot")
        if path and "data" in result:
            import base64

            with open(path, "wb") as f:
                f.write(base64.b64decode(result["data"]))
        return result.get("data")

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
        return await self.evaluate(js)

    async def _close_tab(self) -> None:
        with contextlib.suppress(Exception):
            await self._request("DELETE", f"/tabs/{self._tab_id}")
