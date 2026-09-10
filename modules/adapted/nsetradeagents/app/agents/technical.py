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


try:
    import structlog
except ImportError:
    structlog = None

from app.core.config import settings
from app.utils.indicators import compute_indicators
from app.utils.market_data import extract_ticker_df, safe_yf_download

logger = structlog.get_logger() if structlog else None


def _compute_signal(ind: dict) -> str:
    """Derive BUY, HOLD or SELL from trend and RSI.

    Price below either moving average is HOLD regardless of momentum.
    Above them, RSI over the ceiling is SELL and inside the band is BUY.
    """
    current_price = ind.get("current_price", 0)
    sma50 = ind.get("sma50") or 0
    sma200 = ind.get("sma200") or 0
    rsi = ind.get("rsi", 50)

    if sma200 and current_price < sma200:
        return "HOLD"
    if current_price < sma50:
        return "HOLD"
    if rsi > settings.rsi_max:
        return "SELL"
    if settings.rsi_min <= rsi <= settings.rsi_max:
        return "BUY"
    return "HOLD"


def _compute_strength(ind: dict) -> int:
    """Rate how cleanly a setup meets the swing criteria, 0-100.

    Weighted across RSI position in the ideal zone, MACD direction, volume
    conviction, and how extended the move already is.
    """
    rsi = ind.get("rsi", 50)
    macd_hist_trend = ind.get("macd_hist_trend", "mixed")
    volume_ratio = ind.get("volume_ratio", 0)
    momentum_5d = ind.get("momentum_5d", 0)

    score = 0

    if 62 <= rsi <= 67:
        score += 30
    elif 55 <= rsi <= 70:
        score += 20
    else:
        score += 5

    if macd_hist_trend == "expanding":
        score += 25
    elif macd_hist_trend == "mixed":
        score += 15

    if volume_ratio >= 2.0:
        score += 25
    elif volume_ratio >= 1.5:
        score += 15

    if momentum_5d <= 8:
        score += 20
    elif momentum_5d <= 10:
        score += 10

    return min(score, 100)


def _compute_summary(ind: dict, signal: str, strength: int) -> str:
    """One-line readable summary of the signal and the indicators behind it."""
    rsi = ind.get("rsi", 0)
    macd_trend = ind.get("macd_hist_trend", "mixed")
    volume_ratio = ind.get("volume_ratio", 0)
    momentum_5d = ind.get("momentum_5d", 0)
    return (
        f"{signal} (strength {strength}): RSI {rsi:.1f}, MACD {macd_trend}, "
        f"VolRatio {volume_ratio:.2f}, Mom5d {momentum_5d:.1f}%"
    )
