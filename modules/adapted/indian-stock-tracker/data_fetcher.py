import datetime
import io
from typing import List, Tuple

import pandas as pd
import pytz
import requests
from data_sources import DEFAULT_SOURCES, fetch_with_fallback, resolve_name
from models import Asset, DailyPrice, get_session
from sqlalchemy.orm import Session


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


def get_nifty50_symbols() -> list[str]:
    """
    Fetch Nifty 50 symbols from NSE India.
    Returns a list of symbols (without .NS suffix).
    """
    print("Fetching Nifty 50 symbols from NSE...")
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        df = pd.read_csv(io.StringIO(response.text))
        nse_symbols = df["Symbol"].tolist()
        print(f"Successfully fetched {len(nse_symbols)} Nifty 50 symbols.")
        return nse_symbols
    except Exception as e:
        print(f"Failed to download Nifty 50 list from NSE: {e}")
        try:
            from data_sources import NSESource

            print("NSESource available but cannot fetch constituent list; returning empty.")
            return []
        except ImportError:
            print("NSESource not available either.")
            return []


def is_trading_day(date: datetime.date) -> bool:
    """Check if a date is a weekday (Monday-Friday) - trading days only."""
    return date.weekday() < 5


def get_default_symbols() -> list[tuple[str, str]]:
    """
    Get the complete list of default symbols to track.
    Returns Nifty 50 equities only (mutual funds tracked separately in mutual_funds.db).
    """
    nifty50_symbols = get_nifty50_symbols()
    return [(symbol, "equity") for symbol in nifty50_symbols]
