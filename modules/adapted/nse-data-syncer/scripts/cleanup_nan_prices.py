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
One-time cleanup script: Remove rows from daily_prices where close_price is NaN.
PostgreSQL stores NaN as a special float value that Prisma cannot convert, causing
the /stocks page to crash with: "Could not convert value NaN of the field `close_price`"

Run this once to fix the existing bad data, then the fixed database.py will prevent future NaN insertions.
"""

import os

from dotenv import load_dotenv

# Load env
if not os.getenv("DATABASE_URL"):
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pathlib import Path

    load_dotenv(Path(__file__).parent.parent / "web" / ".env")

from sqlalchemy import create_engine, text

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    msg = "DATABASE_URL environment variable is not set."
    raise ValueError(msg)

engine = create_engine(DB_URL)

with engine.connect() as conn:
    # Count affected rows first
    count_result = conn.execute(
        text("""
        SELECT COUNT(*) FROM daily_prices
        WHERE close_price = 'NaN'::float
           OR open_price = 'NaN'::float
           OR high_price = 'NaN'::float
           OR low_price = 'NaN'::float
    """)
    )
    count = count_result.scalar()
    print(f"Found {count} rows with NaN price values.")

    if count > 0:
        # Delete rows where close_price is NaN (critical field for Prisma)
        delete_result = conn.execute(
            text("""
            DELETE FROM daily_prices
            WHERE close_price = 'NaN'::float
        """)
        )
        deleted = delete_result.rowcount
        print(f"Deleted {deleted} rows with NaN close_price.")

        # For remaining rows, set NaN open/high/low to NULL (less critical)
        conn.execute(
            text("""
            UPDATE daily_prices
            SET
                open_price = CASE WHEN open_price = 'NaN'::float THEN NULL ELSE open_price END,
                high_price = CASE WHEN high_price = 'NaN'::float THEN NULL ELSE high_price END,
                low_price  = CASE WHEN low_price  = 'NaN'::float THEN NULL ELSE low_price  END
            WHERE
                open_price = 'NaN'::float
                OR high_price = 'NaN'::float
                OR low_price = 'NaN'::float
        """)
        )
        print("Replaced remaining NaN open/high/low values with NULL.")

        conn.commit()
        print("✅ Cleanup complete. The /stocks page should now work.")
    else:
        print("✅ No NaN rows found. Database is clean.")
