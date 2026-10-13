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


# utils/symbol_utils.py
"""
Shared symbol classification helpers used across the sandbox and other modules.
"""

from database.token_db_enhanced import fno_search_symbols
from utils.constants import CRYPTO_EXCHANGES, FNO_EXCHANGES, INSTRUMENT_PERPFUT


def get_underlying_quote_symbol(base_symbol: str, exchange: str) -> str:
    """Return the quote symbol for an underlying, appending the crypto quote currency if needed.

    For crypto exchanges: canonical perpetual (e.g. BTCUSD.P)
    For all other exchanges: base_symbol unchanged
    """
    if exchange.upper() in CRYPTO_EXCHANGES:
        _perp = fno_search_symbols(
            underlying=base_symbol.upper(),
            exchange=exchange,
            instrumenttype=INSTRUMENT_PERPFUT,
            limit=1,
        )
        if _perp:
            return _perp[0]["symbol"]
        return f"{base_symbol.upper()}USD.P"
    return base_symbol


def is_option(symbol: str, exchange: str) -> bool:
    """Check if symbol is an option based on exchange and canonical symbol suffix."""
    # All exchanges (including CRYPTO) use canonical CE/PE suffix convention.
    # CRYPTO canonical format: BTC28FEB2580000CE / BTC28FEB2580000PE (no dashes)
    if exchange in FNO_EXCHANGES:
        return symbol.endswith("CE") or symbol.endswith("PE")
    return False


def is_future(symbol: str, exchange: str) -> bool:
    """Check if symbol is a future (or perpetual) based on exchange and canonical symbol suffix."""
    # For CRYPTO: dated futures end with FUT; perpetuals (e.g. BTCUSDT) are also futures.
    # Both are non-options so: is_future ≡ not is_option for the CRYPTO exchange.
    if exchange in CRYPTO_EXCHANGES:
        return not (symbol.endswith("CE") or symbol.endswith("PE"))
    if exchange in FNO_EXCHANGES - CRYPTO_EXCHANGES:
        return symbol.endswith("FUT")
    return False
