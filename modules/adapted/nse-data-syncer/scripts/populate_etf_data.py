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
from datetime import datetime

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Load environment variables from web/.env
load_dotenv("web/.env")

# Ensure we can import from app
sys.path.append(os.getcwd())

from app.database import ETF, Base, DatabaseManager, ETFDailyPrice

# Database URL - using PostgreSQL from environment
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    msg = "DATABASE_URL environment variable is not set."
    raise ValueError(msg)

START_DATE = "2020-01-01"  # Get 5+ years of data
CSV_PATH = "data/MW-ETF-22-Apr-2026.csv"


def parse_etf_csv():
    """Parse the ETF CSV file and extract ETF details."""
    print(f"Reading ETF data from {CSV_PATH}...")

    # Read CSV - note the unusual format with quotes and newlines in headers
    df = pd.read_csv(CSV_PATH)

    # Clean up column names (remove newlines and extra spaces)
    df.columns = df.columns.str.replace("\n", " ").str.strip()

    etf_data = []
    for _, row in df.iterrows():
        symbol = str(row.get("SYMBOL", "")).strip()
        if not symbol or symbol == "nan":
            continue

        # Parse NAV - handle comma-separated numbers
        nav_value = None
        if pd.notna(row.get("NAV")) and row.get("NAV") != "":
            try:
                nav_str = str(row.get("NAV")).replace(",", "")
                nav_value = float(nav_str)
            except (ValueError, AttributeError):
                nav_value = None

        etf_data.append(
            {
                "symbol": symbol,
                "name": str(row.get("SYMBOL", "")).strip(),  # Using symbol as name for now
                "underlying_asset": str(row.get("UNDERLYING ASSET", "")).strip()
                if pd.notna(row.get("UNDERLYING ASSET"))
                else None,
                "nav": nav_value,
            }
        )

    print(f"Parsed {len(etf_data)} ETFs from CSV")
    return etf_data


def populate_etf_data():
    print(f"Populating ETF database at {DB_URL}...")

    # Initialize DB
    db = DatabaseManager(db_url=DB_URL)

    # Create tables if they don't exist
    Base.metadata.create_all(db.engine)
    print("ETF tables created/verified")

    # Parse CSV
    etf_list = parse_etf_csv()

    # Insert ETFs into DB
    print("Inserting ETFs into database...")
    etf_map = {}  # symbol -> id

    for etf_data in etf_list:
        etf_id = db.insert_etf(etf_data["symbol"], etf_data)
        if etf_id:
            etf_map[etf_data["symbol"]] = etf_id

    print(f"Total ETFs in database: {len(etf_map)}")

    # Fetch OHLCV Data
    symbols = list(etf_map.keys())
    batch_size = 50
    total = len(symbols)

    print(f"\nFetching historical data for {total} ETFs...")
    print(f"Start date: {START_DATE}")

    successful = 0
    failed = 0

    for i in range(0, total, batch_size):
        batch = symbols[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size

        print(f"\nProcessing batch {batch_num}/{total_batches} ({len(batch)} ETFs)...")

        # Add .NS suffix for NSE
        yf_symbols = [f"{s}.NS" for s in batch]

        try:
            data = yf.download(
                yf_symbols, start=START_DATE, group_by="ticker", threads=True, progress=False, auto_adjust=False
            )

            if data.empty:
                print(f"  No data returned for batch {batch_num}")
                failed += len(batch)
                continue

            # Process each ETF
            for symbol in batch:
                yf_sym = f"{symbol}.NS"
                etf_id = etf_map[symbol]

                try:
                    # Handle single vs multiple symbols
                    if len(batch) == 1:
                        etf_df = data.copy()
                    else:
                        if yf_sym not in data.columns:
                            print(f"  ⚠️  {symbol}: No data available")
                            failed += 1
                            continue
                        etf_df = data[yf_sym].copy()

                    # Drop rows with no close price
                    etf_df = etf_df.dropna(subset=["Close"])

                    if etf_df.empty:
                        print(f"  ⚠️  {symbol}: No valid data")
                        failed += 1
                        continue

                    # Insert daily prices
                    db.insert_etf_daily_prices(etf_id, etf_df)

                    # Calculate and update performance metrics
                    db.update_etf_performance_metrics(etf_id)

                    print(f"  ✓ {symbol}: {len(etf_df)} records")
                    successful += 1

                except Exception as e:
                    print(f"  ✗ {symbol}: Error - {e}")
                    failed += 1

        except Exception as e:
            print(f"Error in batch {batch_num}: {e}")
            failed += len(batch)
            import traceback

            traceback.print_exc()

    print(f"\n{'=' * 60}")
    print("ETF Data Population Complete!")
    print(f"{'=' * 60}")
    print(f"Total ETFs: {total}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    populate_etf_data()
