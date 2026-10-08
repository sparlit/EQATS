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
from events import GTTModifyFailedEvent
from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from limiter import limiter
from marshmallow import ValidationError
from restx_api.schemas import ModifyGTTOrderSchema
from services.modify_gtt_order_service import emit_analyzer_error, modify_gtt_order
from utils.event_bus import bus
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace("modify_gtt_order", description="Modify GTT Order API")

logger = get_logger(__name__)
modify_gtt_schema = ModifyGTTOrderSchema()


@api.route("/", strict_slashes=False)
class ModifyGTTOrder(Resource):
    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        """Modify an active GTT — replaces trigger prices, legs, and condition."""
        try:
            data = request.json or {}

            try:
                order_data = modify_gtt_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                if get_analyze_mode():
                    return make_response(jsonify(emit_analyzer_error(data, error_message)), 400)
                error_response = {"status": "error", "message": error_message}
                safe_request = {k: v for k, v in data.items() if k != "apikey"}
                bus.publish(
                    GTTModifyFailedEvent(
                        mode="live",
                        api_type="modifygttorder",
                        symbol=data.get("symbol", ""),
                        trigger_id=data.get("trigger_id", ""),
                        request_data=safe_request,
                        response_data=error_response,
                        error_message=error_message,
                    )
                )
                return make_response(jsonify(error_response), 400)

            api_key = order_data.pop("apikey", None)

            success, response_data, status_code = modify_gtt_order(
                order_data=order_data, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in ModifyGTTOrder endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
