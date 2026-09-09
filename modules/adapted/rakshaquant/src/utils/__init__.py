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
Utilities module for RakshaQuant.

Provides common utilities:
- Rate limiting for API calls
- TTL caching for expensive operations
- Error types for structured exception handling
- Circuit breaker for resilience
- Event bus for pub/sub communication
"""

from .cache import TTLCache, cached, get_news_cache, get_quote_cache, get_sentiment_cache
from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    get_broker_circuit_breaker,
    get_groq_circuit_breaker,
    get_market_data_circuit_breaker,
)
from .errors import (
    BrokerConnectionError,
    ConfigurationError,
    InsufficientFundsError,
    LLMResponseError,
    MarketDataError,
    OrderRejectedError,
    RateLimitError,
    TradingError,
    get_retry_delay,
    is_retryable_error,
)
from .events import (
    EventBus,
    EventType,
    TradingEvent,
    get_event_bus,
)
from .rate_limiter import RateLimiter, get_groq_limiter, rate_limited

__all__ = [
    "BrokerConnectionError",
    # Circuit breaker
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "ConfigurationError",
    # Events
    "EventBus",
    "EventType",
    "InsufficientFundsError",
    "LLMResponseError",
    "MarketDataError",
    "OrderRejectedError",
    "RateLimitError",
    # Rate limiting
    "RateLimiter",
    # Caching
    "TTLCache",
    # Errors
    "TradingError",
    "TradingEvent",
    "cached",
    "get_broker_circuit_breaker",
    "get_event_bus",
    "get_groq_circuit_breaker",
    "get_groq_limiter",
    "get_market_data_circuit_breaker",
    "get_news_cache",
    "get_quote_cache",
    "get_retry_delay",
    "get_sentiment_cache",
    "is_retryable_error",
    "rate_limited",
]
