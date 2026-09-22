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


import io

import pandas as pd
import requests
import structlog

logger = structlog.get_logger()

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com",
}

NSE_SOURCES = [
    (
        "Nifty Smallcap 250",
        "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    ),
    (
        "Nifty Midcap 150",
        "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    ),
]


def fetch_universe() -> list[str]:
    """Fetch the smallcap and midcap universe from NSE's published CSV lists.

    Returns tickers in yfinance format, e.g. ['TITAN.NS'].
    """
    tickers: list[str] = []

    for name, url in NSE_SOURCES:
        try:
            logger.info("fetching_universe", source=name)
            resp = requests.get(url, headers=NSE_HEADERS, timeout=15)
            if resp.status_code != 200:
                msg = f"HTTP {resp.status_code}"
                raise Exception(msg)

            df = pd.read_csv(io.StringIO(resp.text))
            symbol_col = next((c for c in df.columns if "symbol" in c.lower()), None)

            if not symbol_col:
                logger.warning("no_symbol_column", source=name)
                continue

            symbols = df[symbol_col].dropna().astype(str).str.strip().str.upper().tolist()
            valid = [s for s in symbols if 2 <= len(s) <= 20]
            tickers += [f"{s}.NS" for s in valid]
            logger.info("universe_fetched", source=name, count=len(valid))

        except Exception as e:
            logger.exception("universe_fetch_failed", source=name, error=str(e))

    # Deduplicate
    seen = set()
    unique = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    logger.info("universe_ready", total=len(unique))
    return unique
