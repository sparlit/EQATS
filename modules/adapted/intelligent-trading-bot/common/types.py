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


from decimal import Decimal
from enum import Enum


class Venue(Enum):
    YAHOO = "yahoo"
    BINANCE = "binance"
    MT5 = "mt5"


class AccountBalances:
    """
    Available assets for trade
    """

    # Can be set by the sync/recover function or updated by the trading algorithm
    base_quantity = "0.04108219"  # BTC owned (on account, already bought, available for trade)
    quote_quantity = "1000.0"  # USDT owned (on account, available for trade)


# mt5.AccountInfo
class MT5AccountInfo:
    balance: Decimal = "10000"
    equity: Decimal = "10000"
    margin: Decimal = "0"
    margin_free: Decimal = "10000"
    margin_level: Decimal = "10000"
    profit: Decimal = "0"
    login: int = 0
    currency: str = "USD"
    name: str = ""
    server: str = ""
    leverage: int = 1
