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
NSE data cache — bridges the datacenter-IP block.

NSE blocks cloud/datacenter IPs (Render, etc.) but allows GitHub Actions runners.
So a daily Action fetches FII/DII + corporate events and commits them to
data/nse_cache.json; the deployed backend reads that JSON (locally if present,
else from GitHub raw) when its own direct NSE call is blocked.
"""

import json
from datetime import datetime

import requests
from loguru import logger

from config import DATA_DIR

CACHE_FILE = DATA_DIR / "nse_cache.json"
GITHUB_RAW = "https://raw.githubusercontent.com/agrawalarnav129-ui/jarvis-trading/main/data/nse_cache.json"

_mem: dict | None = None


def write_cache(fii_dii: dict, corporate: list) -> None:
    """Persist NSE-sourced data (called by the GitHub Action where NSE is reachable)."""
    payload = {
        "updated": datetime.utcnow().isoformat() + "Z",
        "fii_dii": fii_dii,
        "corporate": corporate,
    }
    CACHE_FILE.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("NSE cache written: {}", CACHE_FILE)


def read_cache() -> dict:
    """Read cache: local file first (committed in repo), else GitHub raw, else {}."""
    global _mem
    if _mem is not None:
        return _mem
    # Local committed copy (present on the deployed build)
    if CACHE_FILE.exists():
        try:
            _mem = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            return _mem
        except Exception as exc:
            logger.warning("Local NSE cache unreadable: {}", exc)
    # Fall back to GitHub raw (fresh between deploys)
    try:
        r = requests.get(GITHUB_RAW, timeout=10)
        if r.status_code == 200:
            _mem = r.json()
            return _mem
    except Exception as exc:
        logger.debug("GitHub-raw NSE cache fetch failed: {}", exc)
    _mem = {}
    return _mem
