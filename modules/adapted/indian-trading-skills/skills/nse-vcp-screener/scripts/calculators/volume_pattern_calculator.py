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
Volume dry-up pattern calculator for VCP screening.
Measures whether volume is declining as the pattern tightens — a key VCP characteristic.
"""

import pandas as pd


def calculate_volume_pattern(df: pd.DataFrame) -> dict:
    """
    Calculate volume dry-up ratio and score.

    Args:
        df: DataFrame with 'Volume' column, at least 50 rows.

    Returns:
        dict with dry_up_ratio, score, and details.
    """
    if len(df) < 50 or "Volume" not in df.columns:
        return {
            "dry_up_ratio": 1.0,
            "score": 0.0,
            "details": {"error": "Insufficient data or no volume column"},
        }

    vol = df["Volume"]

    avg_50 = float(vol.tail(50).mean())
    avg_10 = float(vol.tail(10).mean())

    if avg_50 <= 0:
        return {
            "dry_up_ratio": 1.0,
            "score": 0.0,
            "details": {"error": "Zero or negative 50-day average volume"},
        }

    dry_up_ratio = avg_10 / avg_50

    score = _score_dry_up(dry_up_ratio)

    return {
        "dry_up_ratio": round(dry_up_ratio, 3),
        "score": round(score, 1),
        "details": {
            "avg_volume_50d": round(avg_50, 0),
            "avg_volume_10d": round(avg_10, 0),
        },
    }


def _score_dry_up(ratio: float) -> float:
    """Score volume dry-up ratio on 0-100 scale."""
    if ratio < 0.40:
        return 90
    if ratio < 0.50:
        return 80
    if ratio < 0.60:
        return 70
    if ratio < 0.70:
        return 60
    if ratio < 0.80:
        return 45
    if ratio < 0.90:
        return 30
    return 15
