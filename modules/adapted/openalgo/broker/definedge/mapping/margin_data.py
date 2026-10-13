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
# Mapping Definedge Span Calculator API

from broker.definedge.mapping.transform_data import map_exchange, map_product_type
from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform OpenAlgo margin positions to Definedge Span Calculator format.

    Args:
        positions: List of positions in OpenAlgo format

    Returns:
        List of positions in Definedge format
    """
    transformed_positions = []

    for position in positions:
        try:
            # Get broker symbol
            tradingsymbol = get_br_symbol(position["symbol"], position["exchange"])

            if not tradingsymbol:
                logger.warning(
                    f"Broker symbol not found for: {position['symbol']} on {position['exchange']}"
                )
                continue

            # Get symbol info from database which contains expiry, strike, option_type, name
            symbol_info = get_symbol_info(position["symbol"], position["exchange"])

            if not symbol_info:
                logger.warning(
                    f"Symbol info not found for: {position['symbol']} on {position['exchange']}"
                )
                continue

            # Extract details from symbol info (accessing object attributes, not dict)
            expiry = getattr(symbol_info, "expiry", "") or ""
            strike = getattr(symbol_info, "strike", "") or ""
            option_type = getattr(symbol_info, "instrumenttype", "") or ""  # CE or PE
            underlying_name = getattr(symbol_info, "name", "") or ""

            # Calculate open_buy_qty and open_sell_qty based on action
            action = position["action"].upper()
            quantity = int(position["quantity"])

            open_buy_qty = quantity if action == "BUY" else 0
            open_sell_qty = quantity if action == "SELL" else 0

            # Map product type
            product_type = map_product_type(position["product"])

            # Build the transformed position
            transformed = {
                "product_type": product_type,
                "exchange": map_exchange(position["exchange"]),
                "symbol_name": underlying_name,
                "tradingsymbol": tradingsymbol,
                "open_buy_qty": open_buy_qty,
                "open_sell_qty": open_sell_qty,
            }

            # Add expiry for derivatives
            if expiry:
                # Convert expiry format from DD-MMM-YY to DD-MMM-YYYY
                # The API expects format like "23-FEB-2023"
                # Database stores it as "23-FEB-23"
                if len(expiry) == 9 and expiry[7:9].isdigit():  # Format: DD-MMM-YY
                    year_suffix = expiry[7:9]
                    year_prefix = "20" if int(year_suffix) < 50 else "19"
                    expiry_full = f"{expiry[:7]}{year_prefix}{year_suffix}"
                    transformed["expiry"] = expiry_full
                else:
                    transformed["expiry"] = expiry

            # Add strike price for options
            if strike and strike != "":
                transformed["option_strike"] = str(int(float(strike)))

            # Add option type for options (CE/PE)
            if option_type and option_type in ["CE", "PE"]:
                transformed["option_type"] = option_type

            transformed_positions.append(transformed)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    return transformed_positions


def parse_margin_response(response_data):
    """
    Parse Definedge margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Definedge API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check for error response
        if response_data.get("status") == "FAILURE" or response_data.get("status") == "ERROR":
            error_message = response_data.get("message", "Failed to calculate margin")
            return {"status": "error", "message": error_message}

        # Check for success
        if response_data.get("status") != "SUCCESS":
            return {
                "status": "error",
                "message": response_data.get("message", "Unknown error from broker"),
            }

        # Extract margin values from Definedge response
        span_margin = float(response_data.get("span", 0))
        exposure_margin = float(response_data.get("exposure", 0))
        total_margin_required = span_margin + exposure_margin

        # Return standardized OpenAlgo format
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin_required,
                "span_margin": span_margin,
                "exposure_margin": exposure_margin,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
