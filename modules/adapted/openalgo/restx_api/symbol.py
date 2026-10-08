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


import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from limiter import limiter
from marshmallow import ValidationError
from services.symbol_service import get_symbol_info
from utils.logging import get_logger

from .data_schemas import SymbolSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("symbol", description="Symbol information API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
symbol_schema = SymbolSchema()


@api.route("/", strict_slashes=False)
class Symbol(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get symbol information for a given symbol and exchange"""
        try:
            # Validate request data
            symbol_data = symbol_schema.load(request.json)

            # Extract parameters
            api_key = symbol_data.pop("apikey", None)
            symbol = symbol_data["symbol"]
            exchange = symbol_data["exchange"]

            # Call the service function to get symbol information
            success, response_data, status_code = get_symbol_info(
                symbol=symbol, exchange=exchange, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)

        except Exception as e:
            logger.exception(f"Unexpected error in symbol endpoint: {e}")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
