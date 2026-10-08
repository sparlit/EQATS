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
Test 2340 symbols subscription on single pooled connection
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
from datetime import datetime

from openalgo import api

# Initialize client
client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765",
)

# Stats tracking
stats = {"updates": 0, "symbols_with_data": set(), "lock": threading.Lock()}


def on_data(data):
    with stats["lock"]:
        stats["updates"] += 1
        if "symbol" in data:
            stats["symbols_with_data"].add(data["symbol"])


def load_symbols(csv_path, limit=2340):
    """Load symbols from CSV"""
    symbols = []
    paths = [
        csv_path,
        "NSE_SYMBOLS.csv",
        os.path.join(os.path.dirname(__file__), "NSE_SYMBOLS.csv"),
        os.path.join(os.path.dirname(__file__), "../../../NSE_SYMBOLS.csv"),
        "D:/Marketcalls/Openalgo_order_mode/NSE_SYMBOLS.csv",
    ]

    for path in paths:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= limit:
                        break
                    symbol = line.strip()
                    if symbol and not symbol.startswith("#"):
                        symbols.append({"exchange": "NSE", "symbol": symbol})
            print(f"Loaded {len(symbols)} symbols from {path}")
            return symbols

    print("CSV not found, using generated symbols")
    return [{"exchange": "NSE", "symbol": f"SYM{i}"} for i in range(limit)]


def main():
    print("=" * 60)
    print("2340 SYMBOLS SUBSCRIPTION TEST")
    print("=" * 60)

    # Load symbols
    symbols = load_symbols("NSE_SYMBOLS.csv", 2340)
    print(f"Total symbols to subscribe: {len(symbols)}")

    # Connect
    print("\nConnecting...")
    client.connect()
    ws_id = id(client.ws) if hasattr(client, "ws") and client.ws else None
    print(f"Connected! WebSocket ID: {ws_id}")

    # Subscribe in batches
    batch_size = 100
    print(f"\nSubscribing in batches of {batch_size}...")

    start_time = time.time()
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        client.subscribe_ltp(batch, on_data_received=on_data)

        # Check connection is still the same
        current_ws_id = id(client.ws) if hasattr(client, "ws") and client.ws else None
        batch_num = i // batch_size + 1
        total_batches = (len(symbols) + batch_size - 1) // batch_size

        if batch_num % 5 == 0 or batch_num == total_batches:
            print(
                f"  Batch {batch_num}/{total_batches} - WS ID: {current_ws_id} - Same: {current_ws_id == ws_id}"
            )

        time.sleep(0.3)

    subscribe_time = time.time() - start_time
    print(f"\nSubscription complete in {subscribe_time:.2f}s")

    # Monitor for 30 seconds
    print("\nMonitoring for 30 seconds...")
    monitor_start = time.time()

    while time.time() - monitor_start < 30:
        time.sleep(5)
        with stats["lock"]:
            print(
                f"  Updates: {stats['updates']:,} | Active symbols: {len(stats['symbols_with_data'])}"
            )

    # Final stats
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    print(f"Subscribed symbols: {len(symbols)}")
    print(f"Symbols receiving data: {len(stats['symbols_with_data'])}")
    print(f"Total updates: {stats['updates']:,}")
    print(f"Connection reused: {id(client.ws) == ws_id}")
    print(f"WebSocket ID (final): {id(client.ws) if hasattr(client, 'ws') and client.ws else None}")
    print("=" * 60)

    # Cleanup
    print("\nDisconnecting...")
    client.disconnect()
    print("Done!")


if __name__ == "__main__":
    main()
