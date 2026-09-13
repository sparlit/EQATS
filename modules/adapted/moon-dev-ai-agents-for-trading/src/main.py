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
🌙 Moon Dev AI Trading System
Main entry point for the trading system
Built with love by Moon Dev 🚀
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.agents.trading_agent import main as run_agent

if __name__ == "__main__":
    print("🚀 Starting Moon Dev's AI Trading System...")
    print("💫 Remember: Moon Dev says trade safe and smart!")

    try:
        run_agent()
    except KeyboardInterrupt:
        print("\n👋 Moon Dev AI Trading System shutting down gracefully...")
    except Exception as e:
        print(f"❌ Error occurred: {e!s}")
        print("🔧 Moon Dev suggests checking the logs and trying again!")
