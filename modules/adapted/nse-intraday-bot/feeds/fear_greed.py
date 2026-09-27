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
Fear & Greed Index — alternative.me free public API.
Used by BTC strategy: ideal range 25–60 for longs.
"""
import requests

URL = "https://api.alternative.me/fng/?limit=1"


def get_fear_greed() -> dict:
    """
    Returns current Fear & Greed index value and classification.
    Scores 25–60 are ideal for bullish BTC entries.
    """
    try:
        r = requests.get(URL, timeout=8)
        data = r.json()
        item = data["data"][0]
        value = int(item["value"])
        label = item["value_classification"]
        return {
            "value": value,
            "label": label,
            "extreme_fear": value < 25,
            "fear": 25 <= value < 45,
            "neutral": 45 <= value <= 55,
            "greed": 55 < value <= 75,
            "extreme_greed": value > 75,
            "in_ideal_range": 25 <= value <= 60,  # ideal for longs
            "error": None,
        }
    except Exception as e:
        return {
            "value": 50,
            "label": "Neutral",
            "extreme_fear": False,
            "fear": False,
            "neutral": True,
            "greed": False,
            "extreme_greed": False,
            "in_ideal_range": True,
            "error": str(e),
        }
