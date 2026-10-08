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


# blueprints/leverage.py
# Leverage configuration for crypto brokers (Delta Exchange)
# Stores a single common leverage value in leverage_config table.

from database.leverage_db import get_leverage, set_leverage
from flask import Blueprint, jsonify, request
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

leverage_bp = Blueprint("leverage_bp", __name__, url_prefix="/leverage")


@leverage_bp.route("/api/current", methods=["GET"])
@check_session_validity
def get_current():
    """Get the current common leverage setting."""
    return jsonify(
        {
            "status": "success",
            "leverage": get_leverage(),
        }
    )


@leverage_bp.route("/api/update", methods=["POST"])
@check_session_validity
def update_leverage():
    """
    Set common leverage for all crypto futures orders.
    Expects JSON: {"leverage": 10}
    """
    data = request.get_json()
    if data is None or "leverage" not in data:
        return jsonify({"status": "error", "message": "Missing leverage field"}), 400

    try:
        leverage = float(data["leverage"])
        import math

        if math.isnan(leverage) or math.isinf(leverage):
            return jsonify({"status": "error", "message": "Invalid leverage value"}), 400
        if leverage < 0:
            return jsonify({"status": "error", "message": "Leverage cannot be negative"}), 400
        if not leverage.is_integer():
            return jsonify({"status": "error", "message": "Leverage must be a whole number"}), 400
        leverage = int(leverage)
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Invalid leverage value"}), 400

    set_leverage(leverage)

    label = f"{int(leverage)}x" if leverage > 0 else "Default"
    return jsonify(
        {
            "status": "success",
            "message": f"Leverage set to {label}",
        }
    )
