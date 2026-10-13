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


# blueprints/settings.py

from database.settings_db import get_analyze_mode
from flask import Blueprint, jsonify
from services.analyzer_service import MODE_BUSY_MESSAGE, apply_analyze_mode
from utils.keyed_locks import LockBusy
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

settings_bp = Blueprint("settings_bp", __name__, url_prefix="/settings")


@settings_bp.route("/analyze-mode")
@check_session_validity
def get_mode():
    """Get current analyze mode setting"""
    try:
        return jsonify({"analyze_mode": get_analyze_mode()})
    except Exception as e:
        logger.exception(f"Error getting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to get analyze mode"}), 500


@settings_bp.route("/analyze-mode/<int:mode>", methods=["POST"])
@check_session_validity
def set_mode(mode):
    """Set analyze mode setting and manage execution engine thread"""
    try:
        # Set the mode and start or stop the execution engine to match, as
        # one step. This route has only ever managed the engine, not the
        # square-off scheduler or the settlement catch-up, and still does not.
        try:
            apply_analyze_mode(bool(mode), with_scheduler=False, catchup=False)
        except LockBusy:
            return jsonify({"error": MODE_BUSY_MESSAGE}), 409
        mode_name = "Analyze" if mode else "Live"

        return jsonify(
            {
                "success": True,
                "analyze_mode": bool(mode),
                "message": f"Switched to {mode_name} Mode",
            }
        )
    except Exception as e:
        logger.exception(f"Error setting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to set analyze mode"}), 500
