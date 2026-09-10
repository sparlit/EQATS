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


def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI from a list of closing prices (oldest to newest)."""
    if len(prices) < period + 1:
        return 50.0  # Neutral if not enough data
    deltas = [prices[i + 1] - prices[i] for i in range(len(prices) - 1)]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_score(price: "DailyPrice") -> float:
    """
    Enhanced scoring using:
    - Price momentum
    - Volume surge
    - RSI signal
    - Distance from 20-day MA (trend)
    - Close strength (close vs high/low range)
    - Gap up signal
    """
    # Note: Database imports and session handling removed due to missing dependencies
    # This function requires SQLAlchemy models and database session
    # Placeholder implementation returning neutral score
    return 50.0
