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
Daily ADR% (Average Daily Range) calculation for all active stocks.

ADR% = 20-day rolling mean of (high_price / low_price - 1) * 100

Standard swing-trading volatility/tradeability filter (Qullamaggie
convention) - measures how much a stock actually moves intraday,
independent of gaps (unlike ATR, which folds in gap moves via true range).
"""
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))
sys.path.append(base_dir)

from app.database import DatabaseManager, StockPerformance

ADR_WINDOW_DAYS = 20


def calculate_adr():
    print("Starting ADR% Calculation...")
    db = DatabaseManager()
    session = db.Session()

    try:
        stocks = session.execute(text("SELECT id FROM stocks WHERE is_active = true")).fetchall()
        active_stock_ids = [s[0] for s in stocks]
        print(f"Found {len(active_stock_ids)} active stocks.")

        if not active_stock_ids:
            return

        # Ensure StockPerformance records exist for all active stocks (same
        # pattern as app/momentum.py)
        existing_perfs = session.execute(text("SELECT stock_id, id FROM stock_performance")).fetchall()
        existing_map = {p[0]: p[1] for p in existing_perfs}

        missing_ids = [sid for sid in active_stock_ids if sid not in existing_map]
        if missing_ids:
            print(f"Creating {len(missing_ids)} missing StockPerformance records...")
            new_perfs = [{"stock_id": sid} for sid in missing_ids]
            session.bulk_insert_mappings(StockPerformance, new_perfs)
            session.commit()
            existing_perfs = session.execute(text("SELECT stock_id, id FROM stock_performance")).fetchall()
            existing_map = {p[0]: p[1] for p in existing_perfs}

        # 20-day window + buffer for holidays/weekends
        start_date = datetime.now() - timedelta(days=45)

        print("Loading price data...")
        prices_query = text("""
            SELECT stock_id, date, high_price, low_price
            FROM daily_prices
            WHERE date >= :start_date
            ORDER BY stock_id, date ASC
        """)
        rows = session.execute(prices_query, {"start_date": start_date}).fetchall()

        if not rows:
            print("No price data found.")
            return

        df = pd.DataFrame(rows, columns=["stock_id", "date", "high", "low"])
        df["date"] = pd.to_datetime(df["date"])
        df["daily_range_pct"] = (df["high"] / df["low"] - 1) * 100

        def latest_adr(g):
            return g["daily_range_pct"].rolling(window=ADR_WINDOW_DAYS, min_periods=ADR_WINDOW_DAYS).mean().iloc[-1]

        adr_series = df.groupby("stock_id").apply(latest_adr, include_groups=False)
        adr_series = adr_series.dropna()
        print(f"Calculated ADR% for {len(adr_series)} stocks.")

        updates = []
        for stock_id, adr_pct in adr_series.items():
            perf_id = existing_map.get(stock_id)
            if not perf_id:
                continue
            updates.append({"id": perf_id, "adr_pct": float(round(adr_pct, 2))})

        if updates:
            print(f"Updating StockPerformance for {len(updates)} records...")
            session.bulk_update_mappings(StockPerformance, updates)
            session.commit()
            print("Database updated successfully.")

    except Exception as e:
        print(f"Error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    calculate_adr()
