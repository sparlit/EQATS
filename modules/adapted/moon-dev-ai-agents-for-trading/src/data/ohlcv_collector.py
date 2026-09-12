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
🌙 Moon Dev's OHLCV Data Collector
Collects Open-High-Low-Close-Volume data for specified tokens
Built with love by Moon Dev 🚀
"""

import os
import time
from datetime import datetime

import pandas as pd
from termcolor import colored, cprint

from ..core import nice_funcs as n
from ..core.config import *


def collect_token_data(token, days_back=DAYSBACK_4_DATA, timeframe=DATA_TIMEFRAME):
    """Collect OHLCV data for a single token"""
    cprint(f"\n🤖 Moon Dev's AI Agent fetching data for {token}...", "white", "on_blue")

    try:
        # Get data from Birdeye
        data = n.get_data(token, days_back, timeframe)

        if data is None or data.empty:
            cprint(f"❌ Moon Dev's AI Agent couldn't fetch data for {token}", "white", "on_red")
            return None

        cprint(f"📊 Moon Dev's AI Agent processed {len(data)} candles for analysis", "white", "on_blue")

        # Save data if configured
        save_path = f"data/{token}_latest.csv" if SAVE_OHLCV_DATA else f"temp_data/{token}_latest.csv"

        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # Save to CSV
        data.to_csv(save_path)
        cprint(f"💾 Moon Dev's AI Agent cached data for {token[:4]}", "white", "on_green")

        return data

    except Exception as e:
        cprint(f"❌ Moon Dev's AI Agent encountered an error: {e!s}", "white", "on_red")
        return None


def collect_all_tokens():
    """Collect OHLCV data for all monitored tokens"""
    market_data = {}

    cprint("\n🔍 Moon Dev's AI Agent starting market data collection...", "white", "on_blue")

    for token in MONITORED_TOKENS:
        data = collect_token_data(token)
        if data is not None:
            market_data[token] = data

    cprint("\n✨ Moon Dev's AI Agent completed market data collection!", "white", "on_green")

    return market_data


if __name__ == "__main__":
    try:
        collect_all_tokens()
    except KeyboardInterrupt:
        print("\n👋 Moon Dev OHLCV Collector shutting down gracefully...")
    except Exception as e:
        print(f"❌ Error: {e!s}")
        print("🔧 Moon Dev suggests checking the logs and trying again!")
