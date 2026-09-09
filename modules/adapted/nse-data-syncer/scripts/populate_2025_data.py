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
from datetime import date

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from sqlalchemy import create_engine

# Ensure we can import from app
sys.path.append(os.getcwd())

from app.constants import CSV_FILENAME
from app.database import DailyPrice, DatabaseManager, Stock
from app.helpers import get_data_path

DB_URL = "sqlite:///data/stocks.db"
START_DATE = "2025-01-01"


def populate_2025():
    print(f"Populating database at {DB_URL} with data from {START_DATE}...")

    # Initialize DB
    db = DatabaseManager(db_url=DB_URL)

    # Create tables if they don't exist
    from app.database import Base

    Base.metadata.create_all(db.engine)

    # Load Symbols from CSV
    csv_path = get_data_path(CSV_FILENAME)
    print(f"Reading symbols from {csv_path}...")
    df = pd.read_csv(csv_path)

    # Insert Stocks into DB
    print("Ensuring stocks exist in DB...")
    symbol_map = {}  # symbol -> id

    session = db.Session()
    existing_stocks = session.query(Stock).all()
    symbol_map = {s.nse_symbol: s.id for s in existing_stocks}

    new_stocks = []
    for _, row in df.iterrows():
        symbol = row["Symbol"]
        if symbol not in symbol_map:
            new_stocks.append(
                Stock(nse_symbol=symbol, name=row["Company Name"], isin=row.get("ISIN Code"), is_active=True)
            )

    if new_stocks:
        print(f"Adding {len(new_stocks)} new stocks...")
        session.bulk_save_objects(new_stocks)
        session.commit()

        # Update map
        existing_stocks = session.query(Stock).all()
        symbol_map = {s.nse_symbol: s.id for s in existing_stocks}

    session.close()

    # Fetch Data
    symbols = list(symbol_map.keys())
    batch_size = 100
    total = len(symbols)

    print(f"Fetching data for {total} stocks...")

    for i in range(0, total, batch_size):
        batch = symbols[i : i + batch_size]
        print(f"Processing batch {i // batch_size + 1}/{(total + batch_size - 1) // batch_size}...")

        yf_symbols = [f"{s}.NS" for s in batch]

        try:
            data = yf.download(
                yf_symbols, start=START_DATE, group_by="ticker", threads=True, progress=False, auto_adjust=False
            )

            if data.empty:
                continue

            # Process and Insert
            dfs_to_insert = []

            # If single symbol
            if len(batch) == 1:
                # Logic for single symbol if needed, but usually handled by loop below if structured right
                # With group_by='ticker', it usually returns MultiIndex even for one if forced, or we check
                pass

            # Handle MultiIndex
            # If only 1 symbol, yfinance returns single index if we aren't careful,
            # but with multiple symbols it returns MultiIndex.
            # If 1 symbol in batch, we treat it specifically

            if len(batch) == 1:
                symbol = batch[0]
                stock_df = data.copy()  # It's just OHLCV columns
                # Check columns
                if "Close" in stock_df.columns:
                    stock_id = symbol_map[symbol]
                    stock_df["stock_id"] = stock_id
                    stock_df["date"] = stock_df.index

                    # Rename columns
                    stock_df = stock_df.rename(
                        columns={
                            "Open": "open_price",
                            "High": "high_price",
                            "Low": "low_price",
                            "Close": "close_price",
                            "Volume": "volume",
                        }
                    )

                    stock_df = stock_df[
                        ["stock_id", "date", "open_price", "high_price", "low_price", "close_price", "volume"]
                    ]
                    dfs_to_insert.append(stock_df)
            else:
                for symbol in batch:
                    yf_sym = f"{symbol}.NS"
                    if yf_sym not in data.columns:
                        continue

                    stock_df = data[yf_sym].copy()
                    stock_df = stock_df.dropna(subset=["Close"])

                    if stock_df.empty:
                        continue

                    stock_id = symbol_map[symbol]
                    stock_df["stock_id"] = stock_id
                    stock_df["date"] = stock_df.index

                    stock_df = stock_df.rename(
                        columns={
                            "Open": "open_price",
                            "High": "high_price",
                            "Low": "low_price",
                            "Close": "close_price",
                            "Volume": "volume",
                        }
                    )

                    # Select cols
                    cols = ["stock_id", "date", "open_price", "high_price", "low_price", "close_price", "volume"]
                    # Verify cols exist
                    if all(c in stock_df.columns for c in cols):
                        dfs_to_insert.append(stock_df[cols])

            if dfs_to_insert:
                final_df = pd.concat(dfs_to_insert, ignore_index=True)
                # Filter out null dates if any
                final_df = final_df.dropna(subset=["date"])

                # Insert
                final_df.to_sql(
                    "daily_prices", db.engine, if_exists="append", index=False, method="multi", chunksize=1000
                )
                print(f"  Inserted {len(final_df)} rows.")

        except Exception as e:
            print(f"Error in batch: {e}")
            import traceback

            traceback.print_exc()

    print("Data population complete.")


if __name__ == "__main__":
    populate_2025()
