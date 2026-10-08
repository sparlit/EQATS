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


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.telegram_db import get_bot_config, update_bot_config

# Test saving with broadcast disabled
print("Testing broadcast_enabled field:")
print("1. Setting broadcast_enabled to False")
update_bot_config({"broadcast_enabled": False})

config = get_bot_config()
print(f"2. After save - broadcast_enabled: {config.get('broadcast_enabled')}")
print(f"   Type: {type(config.get('broadcast_enabled'))}")

# Try again with True
print("\n3. Setting broadcast_enabled to True")
update_bot_config({"broadcast_enabled": True})

config = get_bot_config()
print(f"4. After save - broadcast_enabled: {config.get('broadcast_enabled')}")
print(f"   Type: {type(config.get('broadcast_enabled'))}")
