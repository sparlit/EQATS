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


# Auto-imported by Python at startup when this dir is on PYTHONPATH. ccxt-python's
# requests session doesn't pick up the proxy env vars, so point its built-in
# httpsProxy (class attribute, inherited by every exchange) at the egress proxy —
# all exchange calls then tunnel through the allowlist. No-op without a proxy set.
import os

_proxy = (
    os.environ.get("HTTPS_PROXY")
    or os.environ.get("https_proxy")
    or os.environ.get("HTTP_PROXY")
    or os.environ.get("http_proxy")
)
if _proxy:
    # Sync ccxt (REST).
    try:
        import ccxt

        ccxt.Exchange.httpsProxy = _proxy
    except Exception:
        # ccxt unavailable — the internal network still blocks any non-proxy egress
        pass
    # Async base used by ccxt.pro (WebSockets / watch*).
    try:
        import ccxt.async_support as _accxt

        _accxt.Exchange.httpsProxy = _proxy
        _accxt.Exchange.wssProxy = _proxy
    except Exception:
        pass
