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
Universe closes cache — powers the Sketch Pattern Finder.

Pattern matching needs recent daily closes for the whole universe. Fetching 500+
symbols on every request is impossible on the cloud backend, so a job (GitHub
Actions, where yfinance works) dumps a compact {symbol: [last N closes]} JSON
that the backend reads (GitHub-raw first, like options_cache.json).
"""

import json
from datetime import datetime

import requests
from loguru import logger

from config import DATA_DIR

CACHE_FILE = DATA_DIR / "closes_cache.json"
GITHUB_RAW = "https://raw.githubusercontent.com/agrawalarnav129-ui/jarvis-trading/main/data/closes_cache.json"
BARS = 260  # daily closes kept per symbol (≈1y → enough for EMA200 / 52-week breadth)


def build_closes_cache(period: str = "18mo") -> dict:
    """Fetch the universe's recent daily closes and write the compact cache."""
    from data.fetcher import fetch_symbols_history, load_universe

    uni = load_universe()
    symbols = uni["symbol"].dropna().astype(str).tolist()
    logger.info("Building closes cache for {} symbols…", len(symbols))

    out: dict[str, list[float]] = {}
    hist = fetch_symbols_history(symbols, period=period, interval="1d")
    for sym, df in hist.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        closes = df["close"].dropna().tail(BARS).round(2).tolist()
        if len(closes) >= 30:
            out[sym] = closes

    payload = {"updated": datetime.utcnow().isoformat() + "Z", "bars": BARS, "data": out}
    CACHE_FILE.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    logger.info("Closes cache written: {} symbols → {}", len(out), CACHE_FILE)
    return payload


def read_closes() -> dict:
    """Read the closes cache — GitHub raw first (fresh), then local build-time copy."""
    try:
        r = requests.get(GITHUB_RAW, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated": None, "bars": BARS, "data": {}}
