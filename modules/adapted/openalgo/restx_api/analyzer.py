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
from restx_api.account_schema import AnalyzerSchema, AnalyzerToggleSchema
from services.analyzer_service import get_analyzer_status, toggle_analyzer_mode
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("analyzer", description="Analyzer Mode API")

# Initialize logger
logger = get_logger(__name__)

# Initialize schemas
analyzer_schema = AnalyzerSchema()
analyzer_toggle_schema = AnalyzerToggleSchema()


@api.route("/", strict_slashes=False)
class AnalyzerStatus(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Get analyzer mode status and statistics"""
        try:
            data = request.json

            # Validate and deserialize input using AnalyzerSchema
            try:
                analyzer_data = analyzer_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                error_response = {"status": "error", "message": error_message}
                log_executor.submit(async_log_order, "analyzer_status", data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = analyzer_data.pop("apikey", None)

            # Call the service function to get analyzer status
            success, response_data, status_code = get_analyzer_status(
                analyzer_data=analyzer_data, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in Analyzer status endpoint.")
            error_message = "An unexpected error occurred"
            error_response = {"status": "error", "message": error_message}
            log_executor.submit(async_log_order, "analyzer_status", data, error_response)
            return make_response(jsonify(error_response), 500)


@api.route("/toggle", strict_slashes=False)
class AnalyzerToggle(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Toggle analyzer mode on/off"""
        try:
            data = request.json

            # Validate and deserialize input using AnalyzerToggleSchema
            try:
                analyzer_data = analyzer_toggle_schema.load(data)
            except ValidationError as err:
                error_message = str(err.messages)
                error_response = {"status": "error", "message": error_message}
                log_executor.submit(async_log_order, "analyzer_toggle", data, error_response)
                return make_response(jsonify(error_response), 400)

            # Extract API key
            api_key = analyzer_data.pop("apikey", None)

            # Call the service function to toggle analyzer mode
            success, response_data, status_code = toggle_analyzer_mode(
                analyzer_data=analyzer_data, api_key=api_key
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in Analyzer toggle endpoint.")
            error_message = "An unexpected error occurred"
            error_response = {"status": "error", "message": error_message}
            log_executor.submit(async_log_order, "analyzer_toggle", data, error_response)
            return make_response(jsonify(error_response), 500)
