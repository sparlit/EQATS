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
IV Smile Blueprint

Serves Implied Volatility Smile data.
Endpoints:
    POST /ivsmile/api/iv-smile-data - Get IV Smile data for all strikes
"""

import re

from database.auth_db import get_api_key_for_tradingview
from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin
from services.iv_smile_service import get_iv_smile_data
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

ivsmile_bp = Blueprint("ivsmile_bp", __name__, url_prefix="/")


@ivsmile_bp.route("/ivsmile/api/iv-smile-data", methods=["POST"])
@cross_origin()
@check_session_validity
def iv_smile_data():
    """Get IV Smile data for all strikes."""
    try:
        login_username = session.get("user")
        if not login_username:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        api_key = get_api_key_for_tradingview(login_username)
        if not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "API key not configured. Please generate an API key in /apikey",
                }
            ), 401

        data = request.get_json(silent=True) or {}
        underlying = data.get("underlying", "").strip()[:20]
        exchange = data.get("exchange", "").strip()[:20]
        expiry_date = data.get("expiry_date", "").strip()[:10]

        if not underlying or not exchange or not expiry_date:
            return jsonify(
                {
                    "status": "error",
                    "message": "underlying, exchange, and expiry_date are required",
                }
            ), 400

        if not re.match(r"^[A-Z0-9]+$", underlying) or not re.match(r"^[A-Z0-9_]+$", exchange):
            return jsonify({"status": "error", "message": "Invalid input format"}), 400

        if not re.match(r"^\d{2}[A-Z]{3}\d{2}$", expiry_date):
            return jsonify(
                {"status": "error", "message": "Invalid expiry_date format. Expected DDMMMYY"}
            ), 400

        success, response, status_code = get_iv_smile_data(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in IV Smile data API: {e}")
        return (
            jsonify({"status": "error", "message": "An error occurred processing your request"}),
            500,
        )
