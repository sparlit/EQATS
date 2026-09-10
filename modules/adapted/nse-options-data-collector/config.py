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
Configuration — symbols, paths, lot sizes.

Add your own symbols to STOCKS list below. Lot sizes are fetched
automatically from the Upstox API via /option/contract endpoint.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"

INDICES = ["NIFTY", "BANKNIFTY"]

STOCKS = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "BHARTIARTL",
    "SBIN",
    "ITC",
    "LT",
    "HINDUNILVR",
    "KOTAKBANK",
    "AXISBANK",
    "MARUTI",
    "SUNPHARMA",
    "TITAN",
    "BAJFINANCE",
    "WIPRO",
    "HCLTECH",
    "ADANIENT",
    "TATAMOTORS",
    "TATASTEEL",
    "POWERGRID",
    "NTPC",
    "ONGC",
    "COALINDIA",
    "JSWSTEEL",
    "DRREDDY",
    "BAJAJFINSV",
    "ASIANPAINT",
    "TECHM",
    "INDUSINDBK",
    "M&M",
    "CIPLA",
    "EICHERMOT",
    "SBILIFE",
]

ALL_SYMBOLS = INDICES + STOCKS

STRIKE_STEP = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50}

INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "VIX": "NSE_INDEX|India VIX",
}

_lot_size_cache: dict[str, int] = {}


def get_lot_size(symbol: str, instrument_key: str | None = None) -> int:
    """Get lot size from API via /option/contract. Cached after first call.

    Falls back to 1 if API fails (data collection doesn't need lot size).
    """
    if symbol in _lot_size_cache:
        return _lot_size_cache[symbol]

    key = instrument_key or INSTRUMENT_KEYS.get(symbol)
    if not key:
        return 1

    try:
        from utils.upstox_data import _BASE, _get

        data = _get(f"{_BASE}/option/contract", {"instrument_key": key}, timeout=10)
        if data and isinstance(data, list) and data:
            lot = int(data[0].get("lot_size", 1) or 1)
            _lot_size_cache[symbol] = lot
            return lot
    except Exception:
        pass
    return 1


def load_env(path: Path | None = None) -> int:
    """Load .env file into os.environ. Returns count of vars loaded."""
    env_path = path or (ROOT_DIR / ".env")
    if not env_path.is_file():
        return 0

    loaded = 0
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1
    return loaded
