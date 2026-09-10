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
Pivot proximity calculator.
Scores how close the current price is to the VCP breakout pivot level.
"""


def calculate_pivot_proximity(current_price: float, pivot: float) -> dict:
    """
    Calculate distance from pivot and score.

    Args:
        current_price: Current stock price
        pivot: Breakout pivot level

    Returns:
        dict with distance_pct, score, and position
    """
    if pivot <= 0 or current_price <= 0:
        return {
            "distance_pct": 0.0,
            "score": 0.0,
            "position": "invalid",
        }

    distance_pct = (pivot - current_price) / pivot * 100

    if distance_pct < 0:
        # Already above pivot (broken out)
        score = 50.0
        position = "above_pivot"
    elif distance_pct <= 3:
        score = 90.0
        position = "near_pivot"
    elif distance_pct <= 5:
        score = 75.0
        position = "approaching_pivot"
    elif distance_pct <= 8:
        score = 60.0
        position = "moderate_distance"
    elif distance_pct <= 12:
        score = 45.0
        position = "far_from_pivot"
    elif distance_pct <= 20:
        score = 30.0
        position = "very_far"
    else:
        score = 15.0
        position = "too_far"

    return {
        "distance_pct": round(abs(distance_pct), 2),
        "score": score,
        "position": position,
    }
