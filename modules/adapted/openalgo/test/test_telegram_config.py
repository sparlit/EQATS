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
Test script to verify Telegram bot configuration saving and loading
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.telegram_db import get_bot_config, update_bot_config


def test_config():
    """Test configuration save and load"""
    print("Testing Telegram Bot Configuration")
    print("=" * 50)

    # Get current config
    print("\n1. Current Configuration:")
    config = get_bot_config()
    for key, value in config.items():
        if key in ["bot_token", "token"]:
            if value:
                print(f"   {key}: {value[:10]}..." if value else f"   {key}: None")
            else:
                print(f"   {key}: None")
        else:
            print(f"   {key}: {value}")

    # Test saving configuration
    print("\n2. Testing Save Configuration:")
    test_config = {
        "bot_token": "test_token_123456789",
        "broadcast_enabled": True,
        "rate_limit_per_minute": 60,
    }

    success = update_bot_config(test_config)
    print(f"   Save result: {'Success' if success else 'Failed'}")

    # Verify saved configuration
    print("\n3. Configuration After Save:")
    config = get_bot_config()
    for key, value in config.items():
        if key in ["bot_token", "token"]:
            if value:
                print(f"   {key}: {value[:10]}..." if value else f"   {key}: None")
            else:
                print(f"   {key}: None")
        else:
            print(f"   {key}: {value}")

    # Check specific fields
    print("\n4. Verification:")
    print(f"   Token saved correctly: {config.get('bot_token', '').startswith('test_token')}")
    print(f"   Broadcast enabled: {config.get('broadcast_enabled')}")
    print(f"   Rate limit: {config.get('rate_limit_per_minute')}")


if __name__ == "__main__":
    test_config()
