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
Binance Perpetual Funding Rate — public endpoint, no API key needed.
Used by BTC strategy: positive funding > 0.05% = danger for longs.
"""
import requests

BINANCE_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
BYBIT_URL = "https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT"


def get_funding_rate(symbol: str = "BTCUSDT") -> dict:
    """
    Returns current funding rate dict.
    Falls back to Bybit if Binance is unreachable.
    """
    result = _try_binance(symbol)
    if result["error"]:
        result = _try_bybit(symbol)
    return result


def _try_binance(symbol: str) -> dict:
    try:
        r = requests.get(BINANCE_URL, params={"symbol": symbol}, timeout=8)
        data = r.json()
        rate = float(data.get("lastFundingRate", 0))
        return _build(rate, "binance")
    except Exception as e:
        return {**_empty(), "error": str(e)}


def _try_bybit(symbol: str) -> dict:
    try:
        r = requests.get(BYBIT_URL, timeout=8)
        data = r.json()
        item = data["result"]["list"][0]
        rate = float(item.get("fundingRate", 0))
        return _build(rate, "bybit")
    except Exception as e:
        return {**_empty(), "error": str(e)}


def _build(rate: float, source: str) -> dict:
    rate_pct = round(rate * 100, 4)
    return {
        "rate": rate,
        "rate_pct": rate_pct,
        "positive": rate > 0,
        "negative": rate < 0,
        # > 0.05% annualised ≈ very expensive for longs
        "danger_for_longs": rate_pct > 0.05,
        # Negative = shorts paying longs = squeeze potential
        "squeeze_potential": rate_pct < -0.01,
        "source": source,
        "error": None,
    }


def _empty() -> dict:
    return {
        "rate": 0,
        "rate_pct": 0,
        "positive": False,
        "negative": False,
        "danger_for_longs": False,
        "squeeze_potential": False,
        "source": None,
        "error": None,
    }
