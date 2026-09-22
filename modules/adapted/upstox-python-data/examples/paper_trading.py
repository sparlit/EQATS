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
Paper trading example — place simulated orders with realistic slippage and costs.

Run: python examples/paper_trading.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paper_broker import PaperBroker
from upstox_data import get_nearest_expiry, get_option_chain, get_spot

broker = PaperBroker(capital=500_000, max_lots=5, max_positions=7)

print("=" * 60)
print("PAPER TRADING DEMO")
print("=" * 60)

# 1. Get market data
spot = get_spot("NIFTY")
print(f"\nNIFTY spot: {spot['ltp']:,.2f}")

expiry = get_nearest_expiry("NIFTY")
print(f"Nearest expiry: {expiry}")

chain = get_option_chain("NIFTY", expiry, num_strikes=5)
atm_row = next((r for r in chain["chain"] if r["is_atm"]), None)

if not atm_row:
    print("No ATM strike found")
    sys.exit(1)

strike = atm_row["strike"]
ce = atm_row["CE"]
pe = atm_row["PE"]

print(f"ATM strike: {strike}")
print(f"  CE: LTP={ce['ltp']:.2f}  bid={ce.get('bid', 'N/A')}  ask={ce.get('ask', 'N/A')}")
print(f"  PE: LTP={pe['ltp']:.2f}  bid={pe.get('bid', 'N/A')}  ask={pe.get('ask', 'N/A')}")

# 2. Place a BUY order with real bid/ask depth
print(f"\n{'─' * 60}")
print("Placing BUY order: 1 lot NIFTY CE (filling at ask, not LTP)...")
result = broker.place_order(
    symbol="NIFTY",
    expiry=expiry,
    strike=strike,
    option_type="CE",
    action="BUY",
    quantity=1,
    option_ltp_hint=ce["ltp"],
    depth_hint={"bid": ce.get("bid", 0), "ask": ce.get("ask", 0)},
    reason="demo trade",
)
print(f"  Status: {result['status']}")
if result["status"] == "SUCCESS":
    print(f"  Position: {result['position_id']}")
    print(f"  Fill price: {result['entry_price']:.2f} (LTP was {ce['ltp']:.2f}, ask was {ce.get('ask', 'N/A')})")
    print(f"  Margin used: INR {result['margin_used']:,.2f}")

    # 3. Set stop loss and target
    sl_result = broker.set_sl_target(result["position_id"], stop_loss_pct=20, target_pct=30)
    print(f"\n  SL: {sl_result['stop_loss']:.2f}  |  Target: {sl_result['target']:.2f}")

    # 4. Simulate price update
    new_price = ce["ltp"] * 1.05
    broker.update_price(result["position_id"], new_price)
    print(f"\n  Price updated to {new_price:.2f}")

    # 5. Check portfolio
    portfolio = broker.get_portfolio()
    print(f"\n{'─' * 60}")
    print("PORTFOLIO:")
    print(f"  Open positions: {portfolio['position_count']}")
    print(f"  Unrealized P&L: INR {portfolio['unrealized_pnl']:,.2f}")
    print(f"  Available capital: INR {portfolio['available_capital']:,.2f}")

    # 6. Close the position
    print(f"\n{'─' * 60}")
    print("Closing position...")
    close = broker.close_position(result["position_id"], "demo exit")
    print(f"  Exit price: {close['exit_price']:.2f}")
    print(f"  Gross P&L: INR {close['gross_pnl']:,.2f}")
    print(f"  Costs: INR {close['costs']['total']:,.2f}")
    print(f"    Brokerage: {close['costs']['brokerage']:.2f}")
    print(f"    STT:       {close['costs']['stt']:.2f}")
    print(f"    GST:       {close['costs']['gst']:.2f}")
    print(f"  Net P&L: INR {close['realized_pnl']:,.2f}")
    print(f"  MFE: INR {close['mfe']:,.2f}  |  MAE: INR {close['mae']:,.2f}")
    print(f"  Hold time: {close['hold_minutes']} min")

# 7. Final portfolio
final = broker.get_portfolio()
print(f"\n{'─' * 60}")
print("FINAL STATE:")
print(f"  Capital: INR {final['available_capital']:,.2f}")
print(f"  Realized P&L today: INR {final['realized_pnl_today']:,.2f}")
print(f"  Trades today: {final['total_trades_today']}")
print("=" * 60)
