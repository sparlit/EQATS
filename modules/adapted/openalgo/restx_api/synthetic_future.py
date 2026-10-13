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


"""
Synthetic Future API Endpoint

POST /api/v1/syntheticfuture

Calculates synthetic future price using ATM Call and Put options.
Does NOT place any orders - returns calculation only.

Request Body:
{
    "apikey": "your_api_key",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28OCT25"
}

Response (Success):
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 25966.05,
    "expiry": "28OCT25",
    "atm_strike": 26000,
    "synthetic_future_price": 26015.25
}

Response (Error):
{
    "status": "error",
    "message": "Could not fetch LTP for Call option: NIFTY28OCT2526000CE"
}
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from limiter import limiter
from marshmallow import ValidationError
from restx_api.schemas import SyntheticFutureSchema
from services.synthetic_future_service import calculate_synthetic_future
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Create namespace
api = Namespace("syntheticfuture", description="Calculate Synthetic Future Price")

# Get rate limit from environment
API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")


@api.route("/", strict_slashes=False)
class SyntheticFuture(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """
        Calculate synthetic future price using ATM options.
        Does NOT place any orders - returns calculation only.
        """
        try:
            # Validate request data
            schema = SyntheticFutureSchema()
            data = schema.load(request.json)

            # Extract parameters
            api_key = data.get("apikey")
            underlying = data.get("underlying")
            exchange = data.get("exchange")
            expiry_date = data.get("expiry_date")

            logger.info(
                f"Synthetic future calculation request: underlying={underlying}, "
                f"exchange={exchange}, expiry={expiry_date}"
            )

            # Call the service function to calculate synthetic future
            success, response_data, status_code = calculate_synthetic_future(
                underlying=underlying, exchange=exchange, expiry_date=expiry_date, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            logger.warning(f"Validation error in synthetic future request: {err.messages}")
            return make_response(
                jsonify({"status": "error", "message": "Validation error", "errors": err.messages}),
                400,
            )
        except Exception:
            logger.exception("An unexpected error occurred in SyntheticFuture endpoint.")
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            return make_response(jsonify(error_response), 500)
