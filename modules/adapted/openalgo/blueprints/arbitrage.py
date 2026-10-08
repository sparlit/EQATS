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


"""Arbitrage Blueprint

Serves the futures calendar-spread arbitrage universe.

Endpoints:
    GET /arbitrage/api/universe?exchanges=NFO,MCX
        Returns the near/next/third-month futures pairs and the de-duplicated
        symbol list to subscribe to over the market-data WebSocket.
"""

from database.auth_db import get_api_key_for_tradingview
from flask import Blueprint, jsonify, request, session
from flask_cors import cross_origin
from services.arbitrage_service import DEFAULT_EXCHANGES, get_arbitrage_universe
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

arbitrage_bp = Blueprint("arbitrage_bp", __name__, url_prefix="/")


@arbitrage_bp.route("/arbitrage/api/universe", methods=["GET"])
@cross_origin()
@check_session_validity
def arbitrage_universe():
    """Return the calendar-spread universe for the requested exchanges."""
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

        raw = (request.args.get("exchanges") or "").strip()
        if raw:
            exchanges = [ex.strip().upper() for ex in raw.split(",") if ex.strip()]
        else:
            exchanges = list(DEFAULT_EXCHANGES)

        success, response, status_code = get_arbitrage_universe(
            exchanges=exchanges,
            api_key=api_key,
        )

        return jsonify(response), status_code

    except Exception as e:
        logger.exception(f"Error in arbitrage universe API: {e}")
        return (
            jsonify({"status": "error", "message": "An error occurred processing your request"}),
            500,
        )
