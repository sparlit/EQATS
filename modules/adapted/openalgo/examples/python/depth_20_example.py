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
OpenAlgo WebSocket 20-Level Market Depth Example
For brokers that support 20-level depth (Dhan NSE/NFO)
"""

import logging
import os
import time

from openalgo import api

# Configure logging to see WebSocket debug output
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Initialize feed client with explicit parameters
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),  # Set OPENALGO_API_KEY in your environment
    host="http://127.0.0.1:5000",  # Replace with your API host
    ws_url="ws://127.0.0.1:8765",  # Explicit WebSocket URL (can be different from REST API host)
)

# Instruments for 20-level depth testing
# Use :20 suffix to request 20-level depth (e.g., "TCS:20")
# NFO also supports 20-level depth
instruments_list = [
    {"exchange": "NSE", "symbol": "TCS:20"},
]


def on_data_received(data):
    print("Market Depth Update:")
    print(data)


# Connect and subscribe
client.connect()
client.subscribe_depth(instruments_list, on_data_received=on_data_received)

# Wait a bit for WebSocket to connect and start receiving data
print("\nWaiting for 20-level depth WebSocket to connect and receive data...")
time.sleep(3)

# Poll Market Depth data a few times
for i in range(15):
    print(f"\nPoll {i + 1}:")
    depth = client.get_depth()
    if depth:
        print(depth)
    else:
        print("No depth data yet...")
    time.sleep(1)

# Cleanup
client.unsubscribe_depth(instruments_list)
client.disconnect()
