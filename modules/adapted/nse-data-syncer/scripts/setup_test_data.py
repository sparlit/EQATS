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

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# Load env vars
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(DATABASE_URL)


def setup_test_data():
    with engine.connect() as conn:
        # 1. Delete 'ABB' from stocks to test insertion
        print("Deleting 'ABB' from stocks...")
        # First delete daily prices for ABB if any (need stock_id)
        result = conn.execute(text("SELECT id FROM stocks WHERE nse_symbol = 'ABB'"))
        row = result.fetchone()
        if row:
            stock_id = row[0]
            conn.execute(text("DELETE FROM daily_prices WHERE stock_id = :id"), {"id": stock_id})
            conn.execute(text("DELETE FROM quarterly_results WHERE stock_id = :id"), {"id": stock_id})
            conn.execute(text("DELETE FROM news WHERE stock_id = :id"), {"id": stock_id})
            conn.execute(text("DELETE FROM sync_tracker WHERE stock_id = :id"), {"id": stock_id})
            conn.execute(text("DELETE FROM stocks WHERE id = :id"), {"id": stock_id})
            conn.execute(text("DELETE FROM stocks WHERE id = :id"), {"id": stock_id})
            conn.execute(text("DELETE FROM stocks WHERE id = :id"), {"id": stock_id})
            print("Deleted 'ABB'.")
        else:
            print("'ABB' not found, ready for insertion test.")

        # 2. Corrupt 'RELIANCE' data to test corporate action detection
        print("Corrupting 'RELIANCE' data...")
        result = conn.execute(text("SELECT id FROM stocks WHERE nse_symbol = 'RELIANCE'"))
        row = result.fetchone()
        if row:
            stock_id = row[0]
            # Get the latest date
            res = conn.execute(
                text("SELECT date, close_price FROM daily_prices WHERE stock_id = :id ORDER BY date DESC LIMIT 1"),
                {"id": stock_id},
            )
            last_rec = res.fetchone()
            if last_rec:
                date, close = last_rec
                new_close = float(close) * 0.5  # Simulate 50% drop (e.g. split)
                print(f"Modifying RELIANCE data for {date}: {close} -> {new_close}")
                conn.execute(
                    text("UPDATE daily_prices SET close_price = :price WHERE stock_id = :id AND date = :date"),
                    {"price": new_close, "id": stock_id, "date": date},
                )
            else:
                print("No data for RELIANCE to corrupt.")
        else:
            print("RELIANCE not found.")

        conn.commit()
        print("Test data setup complete.")


if __name__ == "__main__":
    setup_test_data()
