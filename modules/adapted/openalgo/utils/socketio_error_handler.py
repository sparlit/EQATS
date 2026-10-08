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
Socket.IO Error Handler
Handles common Socket.IO errors like disconnected sessions gracefully
"""

import functools

from flask_socketio import disconnect
from utils.logging import get_logger

logger = get_logger(__name__)


def handle_disconnected_session(f):
    """
    Decorator to handle disconnected session errors in Socket.IO event handlers
    """

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except KeyError as e:
            if str(e) == "'Session is disconnected'":
                logger.debug(f"Socket.IO session already disconnected in {f.__name__}")
                disconnect()
                return None
            raise
        except Exception as e:
            if "Session is disconnected" in str(e):
                logger.debug(f"Socket.IO session disconnected in {f.__name__}: {e}")
                disconnect()
                return None
            raise

    return wrapper


def init_socketio_error_handling(socketio_instance):
    """
    Initialize Socket.IO error handling

    Args:
        socketio_instance: The Flask-SocketIO instance
    """

    @socketio_instance.on_error_default
    def default_error_handler(e):
        """
        Default error handler for all namespaces
        """
        error_msg = str(e)

        # Handle common disconnection errors silently
        if "Session is disconnected" in error_msg:
            logger.debug(f"Socket.IO session disconnected: {error_msg}")
            return False  # Don't emit error to client

        # Log other errors
        logger.error(f"Socket.IO error: {e}")
        return True  # Let the error propagate

    logger.debug("Socket.IO error handling initialized")
