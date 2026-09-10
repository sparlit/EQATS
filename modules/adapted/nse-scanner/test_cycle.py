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
test_cycle.py — Local Test Runner
=================================
Simulates one full pipeline + bot cycle locally.
Validates JSON outputs, charts, news, and logs.
"""

import json
import os
from datetime import date
from pathlib import Path

import main_pipeline

import config
import main


def simulate_pipeline():
    print("\n=== Running Pipeline Simulation ===")
    # Run pipeline (writes telegram_last_scan.json, scan_history.json, health file, logs)
    main_pipeline.run_pipeline()

    # Check outputs
    print("\n--- Pipeline Outputs ---")
    if Path("telegram_last_scan.json").exists():
        scan = json.load(open("telegram_last_scan.json"))
        print(f"Scan Date: {scan['scan_date']}")
        print(f"Total Stocks: {scan['total_stocks']}")
        print("Sample Stock:", scan["stocks"][0] if scan["stocks"] else "None")
    else:
        print("❌ telegram_last_scan.json not found")

    if Path("scan_history.json").exists():
        history = json.load(open("scan_history.json"))
        print(f"Days Stored: {history.get('days_stored', 0)}")
    else:
        print("❌ scan_history.json not found")

    if Path(config.HEALTH_FILE).exists():
        health = json.load(open(config.HEALTH_FILE))
        print(f"Health Status: {health['status']}")
    else:
        print("❌ scan_health.json not found")


def simulate_bot():
    print("\n=== Running Bot Simulation ===")
    # Run bot startup (sends menu to admin)
    main.main()

    # Simulate callbacks
    class DummyUser:
        def __init__(self, id, first_name):
            self.id = id
            self.first_name = first_name
            self.phone_number = None

    user = DummyUser(123456789, "TestUser")

    # Simulate "View All Stocks"
    class DummyQuery:
        def __init__(self, data):
            self.data = data

    print("\n--- Simulating Callback: VIEW_ALL ---")
    main.handle_callback(DummyQuery("VIEW_ALL"), config.TELEGRAM_CHATID, user)

    print("\n--- Simulating Callback: VIEW_NEWS ---")
    main.handle_callback(DummyQuery("VIEW_NEWS"), config.TELEGRAM_CHATID, user)

    # Simulate one chart
    scan = json.load(open("telegram_last_scan.json"))
    if scan["stocks"]:
        symbol = scan["stocks"][0]["symbol"]
        print(f"\n--- Simulating Callback: VIEW_CHART_{symbol} ---")
        main.handle_callback(DummyQuery(f"VIEW_CHART_{symbol}"), config.TELEGRAM_CHATID, user)


if __name__ == "__main__":
    simulate_pipeline()
    simulate_bot()
    print("\n✅ Test cycle complete")
