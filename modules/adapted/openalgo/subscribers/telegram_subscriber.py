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
Telegram subscriber — sends alerts for all order events.

Uses the existing telegram_alert_service.send_order_alert() which already
handles mode detection (ANALYZE vs LIVE prefix) and message formatting.
Called directly from the EventBus thread pool — send_order_alert() handles
its own async dispatch via alert_executor internally.
"""

from services.telegram_alert_service import telegram_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)


def _send_alert(api_type, order_data, response_data, api_key):
    """Wrapper that matches the original dispatch pattern."""
    telegram_alert_service.send_order_alert(
        api_type,
        order_data,
        response_data,
        api_key,
    )


def on_order_placed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_failed(event):
    # Original code does NOT send telegram on order failure — preserve that behavior
    pass


def on_smart_order_no_action(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modified(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modify_failed(event):
    # Original code does NOT send telegram on modify failure
    pass


def on_order_cancelled(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_cancel_failed(event):
    # Original code does NOT send telegram on cancel failure
    pass


def on_all_orders_cancelled(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_position_closed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_basket_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_split_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_options_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_multiorder_completed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_analyzer_error(event):
    # Original code does NOT send telegram on validation errors — preserve behavior
    pass


# --- GTT ------------------------------------------------------------------
#
# A GTT rests for weeks, so the moment that matters is when it fires: an order
# has just been placed without the user asking. That one is always alerted.
# Placement and cancellation are alerted too, matching how order.placed and
# order.cancelled behave. Failures stay silent, as they do for orders.


def on_gtt_placed(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_cancelled(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_modified(event):
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_triggered(event):
    """The GTT fired and an order went in - the alert that matters most."""
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_expired(event):
    """A trigger the user was relying on has lapsed without firing."""
    _send_alert(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_failed(event):
    # Matches on_order_failed: failures are surfaced in the response and the
    # log, not pushed to Telegram.
    pass


def on_gtt_modify_failed(event):
    pass


def on_gtt_cancel_failed(event):
    pass
