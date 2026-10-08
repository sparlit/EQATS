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


#!/usr/bin/env python3
"""
Test that rejected orders appear correctly in the orderbook API response
"""


from database.sandbox_db import init_db
from sandbox.order_manager import OrderManager

# Initialize database
init_db()

# Test user
user_id = "rajandran"

# Get order manager
om = OrderManager(user_id)

# Get orderbook
success, response, code = om.get_orderbook()

print("Orderbook API Response")
print("=" * 60)
print(f"Success: {success}")
print(f"Status Code: {code}")
print("\nResponse:")
print(f"  Status: {response.get('status')}")
print(f"  Mode: {response.get('mode')}")

# Check for rejected orders
if "data" in response:
    data = response["data"]

    # Extract orders list from data dict
    if isinstance(data, dict) and "orders" in data:
        order_list = data["orders"]
        print(f"\n  Total Orders: {len(order_list)}")
    elif isinstance(data, list):
        order_list = data
        print(f"\n  Total Orders: {len(order_list)}")
    else:
        order_list = []
        print("\n  Unexpected data structure")

    # Filter rejected orders
    rejected_orders = [
        o for o in order_list if isinstance(o, dict) and o.get("order_status") == "rejected"
    ]

    if rejected_orders:
        print(f"\n Rejected Orders: {len(rejected_orders)}")
        for order in rejected_orders:
            print(f"\n    Order ID: {order['orderid']}")
            print(f"    Symbol: {order['symbol']}")
            print(f"    Action: {order['action']}")
            print(f"    Quantity: {order['quantity']}")
            print(f"    Product: {order['product']}")
            print(f"    Status: {order['order_status']}")
            print(f"    Rejection Reason: {order.get('rejection_reason', 'N/A')}")
    else:
        print("\n No rejected orders")

    # Check statistics
    if "statistics" in response:
        stats = response["statistics"]
        print("\n Statistics:")
        print(f"    Total Buy Orders: {stats.get('total_buy_orders', 0)}")
        print(f"    Total Sell Orders: {stats.get('total_sell_orders', 0)}")
        print(f"    Open Orders: {stats.get('total_open_orders', 0)}")
        print(f"    Completed Orders: {stats.get('total_completed_orders', 0)}")
        print(f"    Rejected Orders: {stats.get('total_rejected_orders', 0)}")

print("\n" + "=" * 60)
