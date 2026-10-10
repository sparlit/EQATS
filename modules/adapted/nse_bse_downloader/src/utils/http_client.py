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
HTTP client utilities built on aiohttp with sync wrappers.

Provides minimal helpers to fetch text/bytes and stream downloads while
keeping a synchronous facade for existing callers.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from threading import Thread

import aiohttp

from .tls import default_ssl_context


@dataclass
class HTTPStatusError(Exception):
    status: int
    message: str
    url: str

    def __str__(self) -> str:  # pragma: no cover
        return f"HTTP {self.status} for {self.url}: {self.message}"


def _default_headers() -> dict:
    # Conservative default headers suitable for GitHub/raw and general HTTP
    return {
        "User-Agent": ("NSE_BSE_Downloader/1.1 (+https://github.com/pparesh25/NSE_BSE_Downloader)"),
        "Accept": "*/*",
    }


async def _single_use_session(
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> aiohttp.ClientSession:
    client_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else aiohttp.ClientTimeout()
    # Verify against the trust store the application ships with rather than
    # whatever OpenSSL was compiled to look for.  Update metadata, holiday
    # calendars and update archives all pass through this helper.
    connector = aiohttp.TCPConnector(ssl=default_ssl_context())
    effective_headers = _default_headers()
    if headers:
        effective_headers.update(headers)
    return aiohttp.ClientSession(
        timeout=client_timeout,
        headers=effective_headers,
        connector=connector,
    )


async def fetch_text(
    url: str,
    timeout: float | None = None,
    *,
    session: aiohttp.ClientSession | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    owns_session = False
    if session is None:
        session = await _single_use_session(timeout, headers)
        owns_session = True
    try:
        async with session.get(url) as resp:
            if resp.status == 404:
                raise HTTPStatusError(404, "Not Found", url)
            if resp.status >= 400:
                text = await resp.text()
                raise HTTPStatusError(resp.status, text[:200], url)
            return await resp.text()
    finally:
        if owns_session:
            await session.close()


async def fetch_bytes(
    url: str, timeout: float | None = None, *, session: aiohttp.ClientSession | None = None
) -> bytes:
    owns_session = False
    if session is None:
        session = await _single_use_session(timeout)
        owns_session = True
    try:
        async with session.get(url) as resp:
            if resp.status == 404:
                raise HTTPStatusError(404, "Not Found", url)
            if resp.status >= 400:
                text = await resp.text()
                raise HTTPStatusError(resp.status, text[:200], url)
            return await resp.read()
    finally:
        if owns_session:
            await session.close()


async def download_to_file(
    url: str,
    file_path: str,
    timeout: float | None = None,
    *,
    progress: Callable[[int, int], None] | None = None,
    session: aiohttp.ClientSession | None = None,
    max_bytes: int | None = None,
) -> None:
    owns_session = False
    if session is None:
        session = await _single_use_session(timeout)
        owns_session = True
    try:
        async with session.get(url) as resp:
            if resp.status == 404:
                raise HTTPStatusError(404, "Not Found", url)
            if resp.status >= 400:
                text = await resp.text()
                raise HTTPStatusError(resp.status, text[:200], url)
            total = int(resp.headers.get("content-length", 0))
            if max_bytes is not None and total > max_bytes:
                raise ValueError(f"Download exceeds maximum size of {max_bytes} bytes")
            downloaded = 0
            with open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    if chunk:
                        if max_bytes is not None and downloaded + len(chunk) > max_bytes:
                            raise ValueError(f"Download exceeds maximum size of {max_bytes} bytes")
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total)
    finally:
        if owns_session:
            await session.close()


# ---- Sync wrappers ----


def _run_coro_blocking(coro):
    """Run coroutine safely even if an event loop is running elsewhere.
    Uses a dedicated thread with its own loop to avoid conflicts.
    """
    result_holder = {}
    error_holder = {}

    def runner():
        try:
            result_holder["result"] = asyncio.run(coro)
        except Exception as e:  # pragma: no cover
            error_holder["error"] = e

    t = Thread(target=runner, daemon=True)
    t.start()
    t.join()

    if "error" in error_holder:
        raise error_holder["error"]
    return result_holder.get("result")


def fetch_text_sync(
    url: str,
    timeout: float | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    return _run_coro_blocking(fetch_text(url, timeout, headers=headers))


def fetch_bytes_sync(url: str, timeout: float | None = None) -> bytes:
    return _run_coro_blocking(fetch_bytes(url, timeout))


def download_to_file_sync(
    url: str,
    file_path: str,
    timeout: float | None = None,
    *,
    progress: Callable[[int, int], None] | None = None,
    max_bytes: int | None = None,
) -> None:
    return _run_coro_blocking(
        download_to_file(
            url,
            file_path,
            timeout,
            progress=progress,
            max_bytes=max_bytes,
        )
    )
