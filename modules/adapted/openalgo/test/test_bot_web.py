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
Test script to verify bot starts properly from web UI
"""

import time

from database.telegram_db import get_bot_config
from services.telegram_bot_service import (
    get_telegram_bot,
    init_bot_sync,
    start_bot_sync,
    stop_bot_sync,
)

# Get config
config = get_bot_config()

if not config.get("token"):
    print("[ERROR] No bot token configured")
    exit(1)

print(f"[INFO] Bot token found: {config['token'][:10]}...")

# Initialize bot
print("[INFO] Initializing bot...")
success, message = init_bot_sync(config["token"], None)

if not success:
    print(f"[ERROR] Failed to initialize: {message}")
    exit(1)

print(f"[OK] {message}")

# Start bot
print("[INFO] Starting bot in polling mode...")
success, message = start_bot_sync()

if not success:
    print(f"[ERROR] Failed to start: {message}")
    exit(1)

print(f"[OK] {message}")

# Check status
bot = get_telegram_bot()
print(f"[STATUS] Bot running: {bot.is_running}")

# Keep running for testing
print("[INFO] Bot is running. Press Ctrl+C to stop.")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[INFO] Stopping bot...")
    success, message = stop_bot_sync()
    print(f"[OK] {message}")
