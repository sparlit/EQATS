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
Daily Index data sync script
Fetches latest OHLCV data for predefined indices and updates performance metrics
"""
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

# Load environment variables
load_dotenv("web/.env")

# Ensure we can import from app
sys.path.append(os.getcwd())

from app.constants import VALIDATION_RECORDS_COUNT
from app.database import DatabaseManager, Index, IndexDailyPrice, IndexPerformance
from app.helpers import validate_data_mismatch

# Database URL
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


def sync_index_daily():
    """Sync daily Index data - fetch latest prices and update performance metrics"""
    print(f"Starting Index daily sync at {datetime.now()}")

    db = DatabaseManager(db_url=DB_URL)

    # Get all active Indices
    index_map = db.get_index_symbol_map()

    if not index_map:
        print("No Indices found in database. Please run setup_indices.py first.")
        return

    print(f"Found {len(index_map)} Indices to sync")

    # Get last 5 trading days to ensure we don't miss any data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)

    successful = 0
    failed = 0

    symbols = list(index_map.keys())

    # We do not append .NS here as they already have the correct format
    try:
        data = yf.download(
            symbols,
            start=start_date.strftime("%Y-%m-%d"),
            end=end_date.strftime("%Y-%m-%d"),
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=False,
        )

        if data.empty:
            print("  No data returned.")
            return

        for symbol in symbols:
            index_id = index_map[symbol]

            try:
                if len(symbols) == 1:
                    index_df = data.copy()
                else:
                    if symbol not in data.columns:
                        print(f"  ⚠️  {symbol}: No data available")
                        failed += 1
                        continue
                    index_df = data[symbol].copy()

                # Drop rows with no close price
                index_df = index_df.dropna(subset=["Close"])

                if index_df.empty:
                    print(f"  ⚠️  {symbol}: No valid data")
                    failed += 1
                    continue

                # Validation: Check for mismatches
                last_records = db.get_index_last_n_records(index_id, n=VALIDATION_RECORDS_COUNT)
                if validate_data_mismatch(symbol, index_df, last_records):
                    print(f"  ⚠️  Mismatch confirmed for {symbol}. Cleaning up and re-syncing...")
                    db.delete_index_prices(index_id)

                    # Re-fetch full history for this specific Index
                    print(f"  🔄  Resyncing {symbol} from scratch...")
                    full_data = yf.download(symbol, start="2000-01-01", progress=False, auto_adjust=False)
                    if not full_data.empty:
                        index_df = full_data
                        print(f"     Resynced {len(index_df)} records.")
                    else:
                        print(f"     Failed to resync {symbol}.")
                        failed += 1
                        continue

                # Insert daily prices (will skip duplicates based on date)
                # Check last synced date to avoid duplicates
                last_synced_date = db.get_index_last_synced_date(index_id)

                if last_synced_date:
                    # Ensure last_synced_date is timezone-naive/aware matching df
                    last_ts = pd.Timestamp(last_synced_date)
                    if index_df.index.tz is not None and last_ts.tz is None:
                        last_ts = last_ts.tz_localize(index_df.index.tz)
                    elif index_df.index.tz is None and last_ts.tz is not None:
                        last_ts = last_ts.tz_convert(None)

                    index_df_to_insert = index_df[index_df.index > last_ts]
                else:
                    index_df_to_insert = index_df

                if not index_df_to_insert.empty:
                    db.insert_index_daily_prices(index_id, index_df_to_insert)
                    print(f"  ✓ {symbol}: {len(index_df_to_insert)} new records synced")
                    successful += 1
                else:
                    print(f"  - {symbol}: No new data")
                    successful += 1

                # Update performance metrics
                db.update_index_performance_metrics(index_id)

            except Exception as e:
                print(f"  ✗ {symbol}: Error - {e}")
                failed += 1

    except Exception as e:
        print(f"Error executing batch: {e}")
        failed += len(symbols)

    print(f"\n{'=' * 60}")
    print("Index Daily Sync Complete!")
    print(f"{'=' * 60}")
    print(f"Total Indices: {len(symbols)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Completed at: {datetime.now()}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    sync_index_daily()
