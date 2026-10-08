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
Volatility Surface Blueprint
Serves 3D implied volatility surface data for index options.
"""

from database.auth_db import get_api_key_for_tradingview, get_auth_token
from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin
from services.vol_surface_service import get_vol_surface_data
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

vol_surface_bp = Blueprint("vol_surface_bp", __name__, url_prefix="/")


@vol_surface_bp.route("/volsurface/api/surface-data", methods=["POST"])
@cross_origin()
@check_session_validity
def surface_data():
    """Get 3D volatility surface data across strikes and expiries."""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "Broker not set in session"}), 400

        login_username = session["user"]
        auth_token = get_auth_token(login_username)
        if auth_token is None:
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
        underlying = data.get("underlying", "").strip()
        exchange = data.get("exchange", "").strip()
        expiry_dates = data.get("expiry_dates", [])
        strike_count = int(data.get("strike_count", 15))

        if not underlying or not exchange:
            return jsonify(
                {"status": "error", "message": "underlying and exchange are required"}
            ), 400

        if not expiry_dates or not isinstance(expiry_dates, list):
            return jsonify(
                {"status": "error", "message": "expiry_dates must be a non-empty list"}
            ), 400

        # Limit to 8 expiries max
        expiry_dates = expiry_dates[:8]
        strike_count = min(max(5, strike_count), 40)

        success, response, status_code = get_vol_surface_data(
            underlying=underlying,
            exchange=exchange,
            expiry_dates=expiry_dates,
            strike_count=strike_count,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in vol surface API: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
