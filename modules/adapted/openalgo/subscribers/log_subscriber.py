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
Log subscriber — handles all order logging for both live and analyze modes.

Live mode  → writes to order_logs table via async_log_order
Analyze mode → writes to analyzer_logs table via async_log_analyzer

Note: These functions are called directly (not via executor.submit) because the
EventBus already dispatches callbacks in its own ThreadPoolExecutor. Double-submitting
to a second pool would waste thread capacity without benefit.
"""

from database.analyzer_db import async_log_analyzer
from database.apilog_db import async_log_order
from utils.logging import get_logger

logger = get_logger(__name__)


def _log_event(event):
    """Route to the correct logging function based on mode."""
    if event.mode == "analyze":
        async_log_analyzer(event.request_data, event.response_data, event.api_type)
    else:
        async_log_order(event.api_type, event.request_data, event.response_data)


# All handlers delegate to _log_event — the EventBus thread pool provides isolation
on_order_placed = _log_event
on_order_failed = _log_event
on_smart_order_no_action = _log_event
on_order_modified = _log_event
on_order_modify_failed = _log_event
on_order_cancelled = _log_event
on_order_cancel_failed = _log_event
on_all_orders_cancelled = _log_event
on_position_closed = _log_event
on_basket_completed = _log_event
on_split_completed = _log_event
on_options_completed = _log_event
on_multiorder_completed = _log_event
on_analyzer_error = _log_event

# GTT. Logged exactly like any other order API call, so a GTT placement shows up
# in the API log (live) or the analyzer log (analyze) alongside everything else.
# Without these the whole GTT surface was invisible: only failures reached the
# log, and only because they route through analyzer.error.
on_gtt_placed = _log_event
on_gtt_failed = _log_event
on_gtt_modified = _log_event
on_gtt_modify_failed = _log_event
on_gtt_cancelled = _log_event
on_gtt_cancel_failed = _log_event
on_gtt_triggered = _log_event
on_gtt_expired = _log_event
