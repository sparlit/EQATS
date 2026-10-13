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


from utils.logging import get_logger

logger = get_logger(__name__)


def get_br_symbol(symbol, exchange):
    """Convert OpenAlgo symbol to DefinedGe Securities symbol format"""
    try:
        # DefinedGe uses similar symbol format to NSE/BSE
        # For equity symbols, remove -EQ suffix if present
        if exchange in ["NSE", "BSE"] and symbol.endswith("-EQ"):
            return symbol[:-3]

        # For derivatives, DefinedGe uses standard format
        return symbol

    except Exception as e:
        logger.error(f"Error converting symbol {symbol}: {e}")
        return symbol


def get_oa_symbol(symbol, exchange):
    """Convert DefinedGe Securities symbol to OpenAlgo symbol format"""
    try:
        # For equity symbols on NSE, add -EQ suffix
        if exchange == "NSE" and not any(x in symbol for x in ["FUT", "CE", "PE"]):
            return f"{symbol}-EQ"

        # For other exchanges and derivatives, return as is
        return symbol

    except Exception as e:
        logger.error(f"Error converting symbol {symbol}: {e}")
        return symbol
