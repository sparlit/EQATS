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


"""Events for sandbox engine-internal state changes (analyze mode only).

These fire when the sandbox layer mutates state outside of a user-driven API
call — pending order fills triggered by live LTP, auto-square-off at the
exchange's MIS cutoff, and T+1 settlement of CNC positions to holdings. The
service-layer events (OrderPlacedEvent, OrderCancelledEvent, etc.) already
cover the user-driven paths.

All carry mode="analyze" so the existing socketio subscriber routes them onto
the `analyzer_update` channel that OrderBook / Positions / Holdings already
listen to.
"""

from dataclasses import dataclass

from events.base import OrderEvent


@dataclass
class SandboxOrderFilledEvent(OrderEvent):
    """Fired when a pending sandbox order (LIMIT/SL/SL-M) fills via live LTP.

    Also fires for MARKET orders that fill immediately on placement; the
    duplicate refresh is harmless since the frontend just refetches.
    """

    topic: str = "sandbox.order_filled"
    orderid: str = ""
    tradeid: str = ""
    symbol: str = ""
    exchange: str = ""
    action: str = ""
    quantity: int = 0
    price: float = 0.0
    product: str = ""
    strategy: str = ""


@dataclass
class SandboxAutoSquareOffEvent(OrderEvent):
    """Fired after the sandbox auto-square-off scheduler completes a cycle.

    Covers both the cancel-open-MIS-orders sweep and the close-MIS-positions
    sweep that run past each exchange's MIS cutoff.
    """

    topic: str = "sandbox.auto_squareoff"
    cancelled_orders: int = 0
    closed_positions: int = 0


@dataclass
class SandboxT1SettlementEvent(OrderEvent):
    """Fired after T+1 settlement moves CNC positions into holdings."""

    topic: str = "sandbox.t1_settlement"
    settled_users: int = 0
    settled_positions: int = 0
