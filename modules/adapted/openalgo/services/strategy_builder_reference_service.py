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


"""Resolve the canonical underlying reference used by Strategy Builder charts."""

from database.token_db_enhanced import fno_search_symbols
from services.option_symbol_service import NO_SPOT_EXCHANGES, resolve_underlying_quote
from utils.constants import CRYPTO_EXCHANGES, INSTRUMENT_PERPFUT

NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
    "NIFTYIT",
    "NIFTYPHARMA",
    "NIFTYBANK",
}

BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}


def get_quote_exchange(base_symbol: str, underlying_exchange: str) -> str:
    """Resolve the exchange used for an underlying quote or history request."""
    upper = (underlying_exchange or "").upper()
    if base_symbol in NSE_INDEX_SYMBOLS:
        return "NSE_INDEX"
    if base_symbol in BSE_INDEX_SYMBOLS:
        return "BSE_INDEX"
    if upper == "NFO":
        return "NSE"
    if upper == "BFO":
        return "BSE"
    if upper in ("NSE_INDEX", "BSE_INDEX"):
        return upper
    return upper


def resolve_strategy_builder_reference(
    base_symbol: str,
    exchange: str,
    underlying_symbol: str | None = None,
    underlying_exchange: str | None = None,
) -> tuple[str, str] | None:
    """Return one symbol/exchange pair for both chart history and latest quote.

    A canonical pair supplied by the option-chain response takes precedence.
    Venues without a tradable spot fall back to their near-month future.
    """
    base = (base_symbol or "").strip().upper()
    venue = (exchange or "").strip().upper()
    if underlying_symbol and underlying_exchange:
        return underlying_symbol.strip().upper(), underlying_exchange.strip().upper()
    if venue in CRYPTO_EXCHANGES:
        perpetuals = fno_search_symbols(
            query=f"{base}USDFUT",
            exchange=venue,
            instrumenttype=INSTRUMENT_PERPFUT,
            limit=1,
        )
        if not perpetuals:
            return None
        perpetual = perpetuals[0]
        return perpetual["symbol"].strip().upper(), (
            perpetual.get("exchange") or venue
        ).strip().upper()
    if venue in NO_SPOT_EXCHANGES:
        return resolve_underlying_quote(base, venue)
    return base, get_quote_exchange(base, venue)
