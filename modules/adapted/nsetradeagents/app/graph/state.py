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


from typing import Any, TypedDict


class TradingState(TypedDict):
    # Input
    """State passed between pipeline nodes.

    Each node returns only the keys it sets. Note that keys not declared here
    are silently discarded by LangGraph, so a typo loses data without error.
    """

    ticker: str
    portfolio_cash: float
    open_positions: int
    open_position_sectors: list[str]

    # Pre-fetched market data (loaded once before parallel agents)
    ticker_df: Any  # pd.DataFrame — 12mo price history
    ticker_info: dict | None  # yf.Ticker(ticker).info
    nifty_df: Any  # pd.DataFrame — Nifty 50 recent data
    vix_df: Any  # pd.DataFrame - India VIX recent data

    # Derived / computed
    current_price: float
    market_context: dict | None
    fundamental_result: dict | None

    # Agent outputs
    technical_signals: dict | None
    risk_result: dict | None

    # Final
    trade_result: dict | None
    rules_score: int | None
    rules_bands: dict | None
    veto_result: dict | None
