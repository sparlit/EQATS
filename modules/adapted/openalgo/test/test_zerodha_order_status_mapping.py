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


from broker.zerodha.mapping.order_data import (
    calculate_order_statistics,
    transform_order_data,
)


def _order(status, order_id="1"):
    return {
        "order_id": order_id,
        "status": status,
        "tradingsymbol": "SBIN",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "quantity": 1,
        "order_type": "SL-M",
        "product": "MIS",
    }


def test_transient_rest_statuses_do_not_inherit_previous_order_status():
    transformed = transform_order_data(
        [
            _order("COMPLETE", "1"),
            _order("OPEN PENDING", "2"),
            _order("VALIDATION PENDING", "3"),
            _order("KITE FUTURE STATE", "4"),
        ]
    )

    assert [order["order_status"] for order in transformed] == [
        "complete",
        "open",
        "open",
        "kite future state",
    ]


def test_first_order_in_flight_has_a_status():
    [transformed] = transform_order_data([_order("OPEN PENDING")])

    assert transformed["order_status"] == "open"


def test_rest_order_book_exposes_trigger_pending_as_actionable_open():
    orders = [_order("TRIGGER PENDING")]
    [transformed] = transform_order_data(orders)

    assert transformed["order_status"] == "open"
    assert calculate_order_statistics(orders)["total_open_orders"] == sum(
        order["order_status"] == "open" for order in transform_order_data(orders)
    )


def test_statistics_count_trigger_pending_and_in_flight_as_open():
    stats = calculate_order_statistics(
        [
            _order("COMPLETE", "1"),
            _order("TRIGGER PENDING", "2"),
            _order("OPEN PENDING", "3"),
            _order("CANCELLED", "4"),
            _order("OPEN", "5"),
            _order("REJECTED", "6"),
        ]
    )

    assert stats == {
        "total_buy_orders": 6,
        "total_sell_orders": 0,
        "total_completed_orders": 1,
        "total_open_orders": 3,
        "total_rejected_orders": 1,
    }
