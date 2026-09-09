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


"""Service layer for stock search functionality."""
import json
import logging
from typing import Any, Dict, List, Optional

import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StockSearchService:
    """Service for searching stocks via Yahoo Finance API."""

    YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
    DEFAULT_SEARCH_LIMIT = 10

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    def search_stocks(self, query: str, limit: int = DEFAULT_SEARCH_LIMIT) -> list[dict[str, Any]]:
        """Search for stocks by query string."""
        if not query:
            return []

        params = {"q": query, "quotesCount": limit, "newsCount": 0}

        try:
            response = self.session.get(self.YAHOO_SEARCH_URL, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            results = []

            for quote in data.get("quotes", []):
                # Only equities
                if quote.get("quoteType") != "EQUITY":
                    continue

                symbol = quote.get("symbol", "")

                # Only Indian NSE/BSE stocks
                if not (symbol.endswith((".NS", ".BO"))):
                    continue

                results.append(
                    {
                        "symbol": symbol,
                        "name": quote.get("longname") or quote.get("shortname") or "",
                        "exchange": quote.get("exchange"),
                        "type": quote.get("quoteType"),
                    }
                )

            return results

        except requests.RequestException as e:
            logger.exception(f"Search failed: {e}")
            return []

    def get_stock_details(self, symbol: str) -> dict[str, Any]:
        """Get detailed stock information for a symbol."""
        # This would be implemented with yfinance in the real implementation
        # For now, we'll return mock data based on the symbol
        f"{symbol.replace('.NS', '.NSE') if symbol.endswith('.NS') else symbol.replace('.BO', '.BSE')}"

        # Mock data based on symbol
        return {
            "symbol": symbol,
            "company_name": f"Mock {symbol}",
            "short_name": f"Mock {symbol.split('.', maxsplit=1)[0]}",
            "sector": "Energy" if "RELIANCE" in symbol else "Technology" if "TECH" in symbol else "Finance",
            "industry": "Conglomerate" if "RELIANCE" in symbol else "Banking" if "BANK" in symbol else "IT",
            "price": 1200.0 if "RELIANCE" in symbol else 800.0,
            "pe_ratio": 25.0 if "RELIANCE" in symbol else 30.0,
            "market_cap": 17565149560832 if "RELIANCE" in symbol else 50000000000,
            "beta": 1.2 if "RELIANCE" in symbol else 1.0,
            "dividend_yield": 1.5 if "RELIANCE" in symbol else 0.0,
            "book_value": 800.0 if "RELIANCE" in symbol else 400.0,
            "website": "https://www.reliance.com" if "RELIANCE" in symbol else "https://www.tcs.com",
            "country": "India",
            "currency": "INR",
        }

    def get_stock_history(self, symbol: str, period: str = "3mo", days: int = 60) -> list[dict[str, Any]]:
        """Get historical stock data from Yahoo Finance."""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)
            if hist is None or hist.empty:
                return []

            # Convert to list of dicts, take last 'days' records
            records = []
            for date, row in hist.iterrows():
                records.append(
                    {
                        "date": date.strftime("%d-%m-%Y"),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "adjusted_close": float(row.get("Adj Close", row["Close"])),
                        "volume": float(row["Volume"]),
                    }
                )
            return records[-days:]
        except Exception as e:
            logger.exception(f"Error fetching history for {symbol}: {e}")
            return []
