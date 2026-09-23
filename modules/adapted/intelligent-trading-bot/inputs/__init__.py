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


from common.types import Venue


def get_collector_functions(venue: Venue):
    if venue == venue.BINANCE:
        from inputs.collector_binance import fetch_klines, health_check

        return fetch_klines, health_check
    if venue == Venue.YAHOO:
        msg = f"Collector functions not implemented for this venue: {venue}"
        raise NotImplementedError(msg)
    if venue == venue.MT5:
        from inputs.collector_mt5 import fetch_klines, health_check

        return fetch_klines, health_check
    msg = f"Unknown collector type: {venue}"
    raise ValueError(msg)


def get_download_functions(venue: Venue):
    if venue == venue.BINANCE:
        from inputs.collector_binance import download_klines

        return download_klines
    if venue == Venue.YAHOO:
        from inputs.collector_yahoo import download_klines

        return download_klines
    if venue == venue.MT5:
        from inputs.collector_mt5 import download_klines

        return download_klines
    msg = f"Unknown venue {venue} or downloader for the venue not implemented"
    raise ValueError(msg)
