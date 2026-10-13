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


# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping TradeSmart (Noren v2) GetOrderMargin API
#
# TradeSmart v2 exposes only a single-order margin calculator (/GetOrderMargin)
# — there is NO basket/multi-leg endpoint in the docs. So the margin path prices
# each leg with GetOrderMargin and sums them (margin_api.py). This forgoes
# spread/hedge netting; if TradeSmart later publishes a basket endpoint, switch
# to the dhan/flattrade basket pattern.

from broker.tradesmart.mapping.transform_data import map_order_type, map_product_type
from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def build_order_margin_payload(position, uid=""):
    """Build a /GetOrderMargin payload for a single OpenAlgo position."""
    oa_symbol = position["symbol"]
    exchange = position["exchange"]
    br_symbol = get_br_symbol(oa_symbol, exchange)
    if not br_symbol:
        logger.warning(f"Symbol not found for {oa_symbol} on {exchange}")
        return None
    if "&" in br_symbol:
        br_symbol = br_symbol.replace("&", "%26")

    userid = uid
    return {
        "uid": userid,
        "actid": userid,
        "exch": exchange,
        "tsym": br_symbol,
        "qty": str(int(position["quantity"])),
        "prc": str(position.get("price", 0) or 0),
        "trgprc": str(position.get("trigger_price", 0) or 0),
        "prd": map_product_type(position.get("product", "NRML")),
        "trantype": "B" if position["action"].upper() == "BUY" else "S",
        "prctyp": map_order_type(position.get("pricetype", "MARKET")),
        "rorgqty": "0",
        "rorgprc": "0",
    }


def parse_order_margin(response_data):
    """Extract the required margin (float) from a GetOrderMargin response.

    Returns ``None`` when the broker reports an error so the caller can surface it.
    """
    if not isinstance(response_data, dict) or response_data.get("stat") != "Ok":
        return None
    # Noren single-order margin commonly returns `ordermargin`; fall back to
    # `marginused` if that key is absent.
    raw = response_data.get("ordermargin")
    if raw is None:
        raw = response_data.get("marginused", 0)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0
