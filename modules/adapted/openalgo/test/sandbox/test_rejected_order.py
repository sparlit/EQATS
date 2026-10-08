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
Test that rejected CNC SELL orders appear in the orderbook
"""

from decimal import Decimal

from database.sandbox_db import SandboxFunds, SandboxOrders, SandboxPositions, db_session, init_db
from sandbox.order_manager import OrderManager

# Initialize database
init_db()

# Test user
user_id = "rajandran"

# Clear ALL previous orders to avoid ID conflicts
SandboxOrders.query.delete()  # Delete ALL orders
SandboxPositions.query.filter_by(user_id=user_id, symbol="ZEEL", product="CNC").delete()
db_session.commit()

# Ensure user has funds
funds = SandboxFunds.query.filter_by(user_id=user_id).first()
if not funds:
    funds = SandboxFunds(
        user_id=user_id,
        total_capital=Decimal("10000000.00"),
        available_balance=Decimal("10000000.00"),
        used_margin=Decimal("0.00"),
    )
    db_session.add(funds)
    db_session.commit()

print("Testing Rejected Order in Orderbook")
print("=" * 60)

# Create order manager
om = OrderManager(user_id)

# Try to place a CNC SELL order without position
print("\n→ Attempting CNC SELL 100 ZEEL (no position)...")
success, response, code = om.place_order(
    {
        "symbol": "ZEEL",
        "exchange": "NSE",
        "action": "SELL",
        "quantity": 100,
        "price_type": "MARKET",
        "product": "CNC",
    }
)

print(f"Response: {response}")
print(f"Success: {success}, Code: {code}")

# Check orderbook
print("\n Checking Orderbook...")
orders = SandboxOrders.query.filter_by(user_id=user_id).all()

print(f"Found {len(orders)} order(s):")
for order in orders:
    print(f"\n  Order ID: {order.orderid}")
    print(f"  Symbol: {order.symbol}")
    print(f"  Action: {order.action}")
    print(f"  Quantity: {order.quantity}")
    print(f"  Product: {order.product}")
    print(f"  Status: {order.order_status}")
    print(f"  Rejection Reason: {order.rejection_reason}")
    print(f"  Margin Blocked: {order.margin_blocked}")

if orders and orders[0].order_status == "rejected":
    print("\n SUCCESS: Rejected order appears in orderbook!")
else:
    print("\n FAIL: Rejected order not in orderbook")

print("=" * 60)
