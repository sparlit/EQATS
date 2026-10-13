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


# blueprints/gc_json.py

import logging
import os
from collections import OrderedDict

from database.auth_db import get_api_key_for_tradingview
from database.symbol import enhanced_search_symbols
from flask import Blueprint, jsonify, render_template, request, session
from utils.session import check_session_validity

logger = logging.getLogger(__name__)

host = os.getenv("HOST_SERVER")

gc_json_bp = Blueprint("gc_json_bp", __name__, url_prefix="/gocharting")


@gc_json_bp.route("/", methods=["GET", "POST"])
@check_session_validity
def gocharting_json():
    if request.method == "POST":
        try:
            symbol_input = request.json.get("symbol")
            exchange = request.json.get("exchange")
            product = request.json.get("product")
            action = request.json.get("action")
            quantity = request.json.get("quantity")

            if not all([symbol_input, exchange, product, action, quantity]):
                logger.error("Missing required fields in GoCharting request")
                return jsonify({"error": "Missing required fields"}), 400

            logger.info(
                f"Processing GoCharting request - Symbol: {symbol_input}, Exchange: {exchange}, Product: {product}, Action: {action}, Quantity: {quantity}"
            )

            # Get actual API key for GoCharting
            api_key = get_api_key_for_tradingview(session.get("user"))
            session.get("broker")

            if not api_key:
                logger.error(f"API key not found for user: {session.get('user')}")
                return jsonify({"error": "API key not found"}), 404

            # Use enhanced search function
            symbols = enhanced_search_symbols(symbol_input, exchange)
            if not symbols:
                logger.warning(f"Symbol not found: {symbol_input}")
                return jsonify({"error": "Symbol not found"}), 404

            symbol_data = symbols[0]  # Take the first match
            logger.info(f"Found matching symbol: {symbol_data.symbol}")

            # Create the JSON response object with OrderedDict for placeorder API
            json_data = OrderedDict(
                [
                    ("apikey", api_key),  # Use actual API key
                    ("strategy", "GoCharting"),
                    ("symbol", symbol_data.symbol),
                    ("action", action.upper()),
                    ("exchange", symbol_data.exchange),
                    ("pricetype", "MARKET"),
                    ("product", product),
                    ("quantity", str(quantity)),
                ]
            )

            logger.info("Successfully generated GoCharting webhook data")
            return jsonify(json_data)

        except Exception as e:
            logger.exception(f"Error processing GoCharting request: {str(e)}")
            return jsonify({"error": str(e)}), 500

    return render_template("gocharting.html", host=host)
