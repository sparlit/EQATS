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

from dotenv import load_dotenv

# Load env from web/.env
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))

# Add the project root to sys.path to allow importing app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import Base, DatabaseManager, StockPerformance


def create_performance_table():
    db = DatabaseManager()
    print("Creating stock_performance table if it doesn't exist...")
    try:
        # This will create the table defined in StockPerformance if it doesn't exist
        StockPerformance.__table__.create(db.engine)
        print("Table 'stock_performance' created successfully.")
    except Exception as e:
        # If table already exists, it might throw an error or just skip depending on driver
        # SQLAlchemy's create_all usually handles existence check, but calling create() on table object directly might not.
        # Let's use create_all with check.
        print(f"Note: {e}")
        print("Attempting via create_all...")
        Base.metadata.create_all(db.engine)
        print("Done.")


if __name__ == "__main__":
    create_performance_table()
