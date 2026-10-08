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
# Mapping AliceBlue V2 API Parameters

from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)


# ─── Product / Order type mappings (OpenAlgo ↔ AliceBlue V2) ──────────────────


def map_product_type(product):
    """Map OpenAlgo product type to AliceBlue V2 product type."""
    mapping = {
        "CNC": "LONGTERM",
        "NRML": "NRML",
        "MIS": "INTRADAY",
    }
    return mapping.get(product, "INTRADAY")


def reverse_map_product_type(product):
    """Map AliceBlue V2 product type back to OpenAlgo product type."""
    mapping = {
        "LONGTERM": "CNC",
        "NRML": "NRML",
        "INTRADAY": "MIS",
        "MTF": "CNC",
        "CNC": "CNC",
        "MIS": "MIS",
        "DELIVERY": "CNC",
    }
    return mapping.get(product, "MIS")


def map_order_type(pricetype):
    """Map OpenAlgo price type to AliceBlue V2 order type."""
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SLM",
    }
    order_type = mapping.get(pricetype)
    if order_type is None:
        # Falling back to MARKET turns a mistyped stop into an order that fills
        # at once instead of resting - the opposite of what was asked for, and
        # "SLM" (AliceBlue's own code for SL-M) is an easy thing to send by
        # mistake. Keep the fallback for compatibility, but say so, as
        # broker/fyers does at the same spot.
        logger.warning(
            f"Unknown pricetype {pricetype!r} received; defaulting to MARKET. "
            f"Valid values: {', '.join(mapping)}"
        )
        return "MARKET"
    return order_type


def reverse_map_order_type(order_type):
    """Map AliceBlue V2 order type back to OpenAlgo price type."""
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SLM": "SL-M",
    }
    return mapping.get(order_type, "MARKET")


# ─── Payload builders (OpenAlgo request → AliceBlue V2 API payload) ──────────


def transform_data(data):
    """
    Transform an OpenAlgo place-order request into an AliceBlue V2 API payload item.
    """
    get_br_symbol(data["symbol"], data["exchange"])
    token = get_token(data["symbol"], data["exchange"])

    return {
        "exchange": data["exchange"],
        "instrumentId": str(int(float(token))),
        "transactionType": data["action"].upper(),
        "quantity": int(data["quantity"]),
        "product": map_product_type(data.get("product", "MIS")),
        "orderComplexity": "REGULAR",
        "orderType": map_order_type(data.get("pricetype", "MARKET")),
        "validity": "DAY",
        "price": str(data.get("price", "0")),
        "slLegPrice": "",
        "targetLegPrice": "",
        "slTriggerPrice": str(data.get("trigger_price", "0")),
        "disclosedQuantity": str(data.get("disclosed_quantity", "")),
        "marketProtectionPercent": "",
        "deviceId": "",
        "trailingSlAmount": "",
        "apiOrderSource": "",
        "algoId": "",
        "orderTag": "openalgo",
    }


def transform_modify_order_data(data):
    """
    Transform an OpenAlgo modify-order request into an AliceBlue V2 API modify payload.
    """
    return {
        "brokerOrderId": str(data.get("orderid")),
        "quantity": int(data.get("quantity", 0)),
        "orderType": map_order_type(data.get("pricetype", "LIMIT")),
        "slTriggerPrice": str(data.get("trigger_price", "0")),
        "price": str(data.get("price", "0")),
        "slLegPrice": "",
        "trailingSlAmount": "",
        "targetLegPrice": "",
        "validity": "DAY",
        "disclosedQuantity": str(data.get("disclosed_quantity", "0")),
        "marketProtection": "",
        "deviceId": "",
    }
