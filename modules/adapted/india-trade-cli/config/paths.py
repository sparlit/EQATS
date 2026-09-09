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


"""Shared filesystem paths for Vibe Trading runtime data."""


import os
from pathlib import Path


def app_data_dir() -> Path:
    """
    Return the writable app data directory.

    Defaults to ~/.trading_platform for desktop/CLI compatibility. Tests,
    CI, and containers can override this with TRADING_PLATFORM_HOME.
    """
    override = os.environ.get("TRADING_PLATFORM_HOME") or os.environ.get("TRADING_PLATFORM_DATA")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".trading_platform"


def app_data_path(*parts: str) -> Path:
    """Return a path inside the writable app data directory."""
    return app_data_dir().joinpath(*parts)


def pdf_output_dir() -> Path:
    """Return the directory used for primary PDF downloads/exports."""
    override = os.environ.get("TRADING_PLATFORM_PDF_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Desktop"
