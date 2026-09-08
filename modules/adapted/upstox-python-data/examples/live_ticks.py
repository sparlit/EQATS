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


"""Stream real-time ticks via WebSocket."""

import sys
import time

sys.path.insert(0, "..")

from upstox_data import INSTRUMENT_KEYS
from upstox_websocket import MarketStreamer


def on_tick(tick):
    key = tick["instrument_key"]
    ltp = tick.get("ltp", 0)

    # Identify symbol
    symbol = "UNKNOWN"
    for name, ikey in INSTRUMENT_KEYS.items():
        if ikey == key:
            symbol = name
            break

    parts = [f"{symbol} LTP={ltp:,.2f}"]
    if "bid" in tick:
        parts.append(f"bid={tick['bid']:.2f}")
    if "ask" in tick:
        parts.append(f"ask={tick['ask']:.2f}")
    if "oi" in tick:
        parts.append(f"OI={tick['oi']:,}")

    print(" | ".join(parts))


def on_disconnect():
    print("WebSocket disconnected!")


# Create and start streamer
ws = MarketStreamer(on_tick=on_tick, on_disconnect=on_disconnect)
ws.start()

# Subscribe to NIFTY and BANKNIFTY indices
keys = [INSTRUMENT_KEYS["NIFTY"], INSTRUMENT_KEYS["BANKNIFTY"]]
ws.subscribe(keys, mode="ltpc")  # ltpc = LTP + last traded qty + close price

# For full depth (bid/ask/OI), use mode="full":
# ws.subscribe(keys, mode="full")

# For option Greeks (IV, delta, gamma, theta, vega), use mode="option_greeks":
# ws.subscribe(["NSE_FO|51834"], mode="option_greeks")

print("Streaming... Press Ctrl+C to stop.\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    ws.stop()
    print("\nStopped.")
