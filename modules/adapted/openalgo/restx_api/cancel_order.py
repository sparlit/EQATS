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

from database.settings_db import get_analyze_mode
from events import OrderFailedEvent
from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from limiter import limiter
from marshmallow import ValidationError
from restx_api.schemas import CancelOrderSchema
from services.cancel_order_service import cancel_order, emit_analyzer_error
from utils.event_bus import bus
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace("cancel_order", description="Cancel Order API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
cancel_order_schema = CancelOrderSchema()


@api.route("/", strict_slashes=False)
class CancelOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Cancel an existing order"""
        try:
            data = request.json

            # Validate and deserialize input
            try:
                order_data = cancel_order_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {"status": "error", "message": error_message}
                bus.publish(
                    OrderFailedEvent(
                        mode="live",
                        api_type="cancelorder",
                        request_data=data,
                        response_data=error_response,
                        error_message=error_message,
                    )
                )
                return make_response(jsonify(error_response), 400)

            # Extract API key and order ID
            api_key = order_data.pop("apikey", None)
            orderid = order_data.get("orderid")

            # Call the service function to cancel the order
            success, response_data, status_code = cancel_order(orderid=orderid, api_key=api_key)

            return make_response(jsonify(response_data), status_code)

        except KeyError as e:
            missing_field = str(e)
            logger.exception(f"KeyError: Missing field {missing_field}")
            error_message = f"A required field is missing: {missing_field}"
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
            error_response = {"status": "error", "message": error_message}
            bus.publish(
                OrderFailedEvent(
                    mode="live",
                    api_type="cancelorder",
                    request_data=data,
                    response_data=error_response,
                    error_message=error_message,
                )
            )
            return make_response(jsonify(error_response), 400)

        except Exception:
            logger.exception("An unexpected error occurred in CancelOrder endpoint.")
            error_message = "An unexpected error occurred"
            if get_analyze_mode():
                return make_response(jsonify(emit_analyzer_error(data, error_message)), 500)
            error_response = {"status": "error", "message": error_message}
            bus.publish(
                OrderFailedEvent(
                    mode="live",
                    api_type="cancelorder",
                    request_data=data,
                    response_data=error_response,
                    error_message=error_message,
                )
            )
            return make_response(jsonify(error_response), 500)
