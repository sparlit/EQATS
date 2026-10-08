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
WhatsApp subscriber — mirrors subscribers/telegram_subscriber.py.

Sends alerts for the same set of order events the Telegram channel covers,
preserving the same "failures don't notify" behavior so a flood of validation
rejections doesn't spam either channel.

Called directly from the EventBus thread pool. send_order_alert() internally
queues onto its own alert_executor pool, so this callback returns quickly
and doesn't block the bus worker.
"""

from services.whatsapp_alert_service import whatsapp_alert_service
from utils.logging import get_logger

logger = get_logger(__name__)


def _send(api_type, order_data, response_data, api_key):
    whatsapp_alert_service.send_order_alert(api_type, order_data, response_data, api_key)


def on_order_placed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_failed(event):
    # Mirror telegram: failures are noisy; don't notify on this channel.
    pass


def on_smart_order_no_action(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modified(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_modify_failed(event):
    pass


def on_order_cancelled(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_order_cancel_failed(event):
    pass


def on_all_orders_cancelled(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_position_closed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_basket_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_split_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_options_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_multiorder_completed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_analyzer_error(event):
    # Mirror telegram: validation errors stay off the chat channels.
    pass


# --- GTT ------------------------------------------------------------------
# Mirrors the telegram handlers so the two alert channels stay in step: a user
# on WhatsApp should not silently miss a GTT firing that a Telegram user sees.
# Failures stay silent here too, matching on_order_failed.


def on_gtt_placed(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_modified(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_cancelled(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_triggered(event):
    """The GTT fired and an order went in without the user asking."""
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_expired(event):
    _send(event.api_type, event.request_data, event.response_data, event.api_key)


def on_gtt_failed(event):
    pass


def on_gtt_modify_failed(event):
    pass


def on_gtt_cancel_failed(event):
    pass
