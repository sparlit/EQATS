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


"""TradingView India scanner adapter for the existing fundamentals fetcher."""

import requests

from data_sources.core import BaseSourceAdapter, SourceRegistry


class TradingViewFundamentalsAdapter(BaseSourceAdapter):
    name = "tradingview"
    datasets = ("fundamentals.tv_batch",)
    url = "https://scanner.tradingview.com/india/scan"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    def __init__(self):
        super().__init__(max_calls=60, window_seconds=60)

    def fetch(self, tickers, columns):
        body = {"symbols": {"tickers": tickers}, "columns": columns}

        def request():
            response = requests.post(self.url, headers=self.headers, json=body, timeout=30)
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data")
            if not isinstance(rows, list):
                raise ValueError("TradingView response has no data list")
            return rows

        return self._execute(request)


def register_adapters(registry: SourceRegistry):
    registry.register(TradingViewFundamentalsAdapter())
