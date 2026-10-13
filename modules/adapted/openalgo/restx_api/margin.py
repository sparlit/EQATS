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

from database.apilog_db import async_log_order
from database.apilog_db import executor as log_executor
from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from limiter import limiter
from marshmallow import ValidationError
from restx_api.schemas import MarginCalculatorSchema
from services.margin_service import calculate_margin
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "50 per second")
api = Namespace("margin", description="Margin Calculator API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
margin_schema = MarginCalculatorSchema()


@api.route("/", strict_slashes=False)
class MarginCalculator(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Calculate margin requirement for a basket of positions"""
        try:
            # Get the request data
            data = request.json

            # Validate and deserialize input using Marshmallow schema
            try:
                validated_data = margin_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                error_response = {"status": "error", "message": error_message}
                log_executor.submit(async_log_order, "margin", data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key without removing it from the validated data
            api_key = validated_data.get("apikey", None)

            # Call the service function to calculate margin
            success, response_data, status_code = calculate_margin(
                margin_data=validated_data, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in Margin Calculator endpoint.")
            error_response = {
                "status": "error",
                "message": "An unexpected error occurred in the API endpoint",
            }
            # Log the error
            try:
                log_executor.submit(
                    async_log_order, "margin", data if "data" in locals() else {}, error_response
                )
            except Exception as e:
                logger.exception(f"Failed to log margin order: {e}")
            return make_response(jsonify(error_response), 500)
