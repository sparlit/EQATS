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
Setup script to initialize indices in the database and pull their maximum historical data.
"""
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

# Load environment variables
load_dotenv("web/.env")

# Ensure we can import from app
sys.path.append(os.getcwd())

from app.database import DatabaseManager

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    msg = "DATABASE_URL environment variable is not set."
    raise ValueError(msg)

INDEX_MAPPING = {
    "^NSEI": "Nifty 50",
    "NIFTYMIDCAP150.NS": "Nifty Midcap 150",
    "NIFTY_LARGEMID250.NS": "Nifty Largemid 250",
    "NIFTYSMLCAP250.NS": "Nifty Smallcap 250",
    "^CRSLDX": "Nifty 500",
}


def setup_indices():
    print("Setting up Indices...")
    db = DatabaseManager(db_url=DB_URL)

    for symbol, name in INDEX_MAPPING.items():
        print(f"Processing index: {name} ({symbol})")
        # Ensure it exists
        index_id = db.insert_index(symbol, {"name": name})

        if not index_id:
            print(f"  Failed to insert {symbol} into indices table.")
            continue

        print(f"  Fetching full history for {symbol}...")
        try:
            data = yf.download(symbol, start="2000-01-01", progress=False, auto_adjust=False)

            if data.empty:
                print(f"  No data found for {symbol}.")
                continue

            # If yf returns MultiIndex when fetching single symbol sometimes
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)

            data = data.dropna(subset=["Close"])

            if data.empty:
                print(f"  No valid close price data found for {symbol}.")
                continue

            # Clear existing prices if any just to ensure clean state
            db.delete_index_prices(index_id)

            # Insert prices
            db.insert_index_daily_prices(index_id, data)
            print(f"  Inserted {len(data)} records for {symbol}.")

            # Update metrics
            db.update_index_performance_metrics(index_id)
            print(f"  Updated performance metrics for {symbol}.")

        except Exception as e:
            print(f"  Error processing {symbol}: {e}")

    print("Finished setting up Indices.")


if __name__ == "__main__":
    setup_indices()
