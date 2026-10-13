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
# Mapping Kotak Neo Margin API

from broker.kotak.mapping.transform_data import (
    map_order_type,
    map_product_type,
    reverse_map_exchange,
)
from database.token_db import get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_position(position):
    """
    Transform a single OpenAlgo margin position to Kotak margin format.

    Note: Kotak margin API accepts only one order at a time, not a batch.

    Args:
        position: Position in OpenAlgo format

    Returns:
        Dict in Kotak margin format or None if transformation fails
    """
    try:
        # Get the token for the symbol
        token = get_token(position["symbol"], position["exchange"])

        if not token:
            logger.warning(
                f"Token not found for symbol: {position['symbol']} on exchange: {position['exchange']}"
            )
            return None

        # Map exchange segment
        exchange_segment = reverse_map_exchange(position["exchange"])
        if not exchange_segment:
            logger.warning(f"Invalid exchange: {position['exchange']}")
            return None

        # Map transaction type
        transaction_type = "B" if position["action"].upper() == "BUY" else "S"

        # Transform the position (all values must be strings for Kotak API)
        transformed = {
            "brkName": "KOTAK",
            "brnchId": "ONLINE",
            "exSeg": exchange_segment,
            "prc": str(position.get("price", "0")),
            "prcTp": map_order_type(position["pricetype"]),
            "prod": map_product_type(position["product"]),
            "qty": str(position["quantity"]),
            "tok": str(token),
            "trnsTp": transaction_type,
        }

        return transformed

    except Exception as e:
        logger.error(f"Error transforming position: {position}, Error: {e}")
        return None


def parse_margin_response(response_data):
    """
    Parse Kotak margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Kotak API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response status is Ok
        if response_data.get("stat") != "Ok":
            error_message = response_data.get("errMsg", "Failed to calculate margin")
            return {"status": "error", "message": error_message}

        # Extract margin data
        # Kotak returns: avlMrgn, reqdMrgn, ordMrgn, mrgnUsd, rmsVldtd, etc.
        total_margin_required = float(response_data.get("reqdMrgn", 0))

        # Return standardized format matching OpenAlgo API specification
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin_required,
                "span_margin": 0,  # Kotak doesn't provide separate span margin
                "exposure_margin": 0,  # Kotak doesn't provide separate exposure margin
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}


def parse_batch_margin_response(responses):
    """
    Parse multiple Kotak margin responses and aggregate them.

    Args:
        responses: List of individual margin responses

    Returns:
        Aggregated margin response
    """
    try:
        total_required_margin = 0

        for response in responses:
            if response.get("status") == "success":
                data = response.get("data", {})
                total_required_margin += data.get("total_margin_required", 0)

        # Return standardized format matching OpenAlgo API specification
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_required_margin,
                "span_margin": 0,  # Kotak doesn't provide separate span margin
                "exposure_margin": 0,  # Kotak doesn't provide separate exposure margin
            },
        }

    except Exception as e:
        logger.error(f"Error parsing batch margin response: {e}")
        return {"status": "error", "message": f"Failed to parse batch margin response: {str(e)}"}
