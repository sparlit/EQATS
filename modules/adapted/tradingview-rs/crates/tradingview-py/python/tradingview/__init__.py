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


"""TradingView Data Provider Python API backed by tradingview-rs."""

# Import native extension
try:
    from tradingview import _tradingview as _tv
except ImportError:
    try:
        import _tradingview as _tv  # type: ignore[no-redef]
    except ImportError:
        _tv = None  # type: ignore[assignment]

if _tv is not None:
    _symbols = [
        "TradingViewError",
        "AuthenticationError",
        "SymbolNotFoundError",
        "ConnectionError",
        "TimeoutError",
        "RateLimitError",
        "ProtocolError",
        "Interval",
        "FinancialPeriod",
        "EconomicImportance",
        "DataServer",
        "Bar",
        "CandleUpdate",
        "HistoricalSeries",
        "QuoteTick",
        "FundamentalPoint",
        "FundamentalSeries",
        "EconomicEvent",
        "QuoteSubscription",
        "BarSubscription",
        "TradingViewClient",
    ]
    for _sym in _symbols:
        if hasattr(_tv, _sym):
            globals()[_sym] = getattr(_tv, _sym)

__all__ = [
    "AuthenticationError",
    "Bar",
    "BarSubscription",
    "CandleUpdate",
    "ConnectionError",
    "DataServer",
    "EconomicEvent",
    "EconomicImportance",
    "FinancialPeriod",
    "FundamentalPoint",
    "FundamentalSeries",
    "HistoricalSeries",
    "Interval",
    "ProtocolError",
    "QuoteSubscription",
    "QuoteTick",
    "RateLimitError",
    "SymbolNotFoundError",
    "TimeoutError",
    "TradingViewClient",
    "TradingViewError",
]
