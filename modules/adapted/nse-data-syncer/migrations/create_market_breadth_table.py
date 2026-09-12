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

from app.helpers import get_project_root
from dotenv import load_dotenv
from sqlalchemy import text

if not os.getenv("DATABASE_URL"):
    load_dotenv(get_project_root() / "web" / ".env")

from app.database import DatabaseManager


def run_migration():
    print("Running migration to create market_breadth_history table...")
    db = DatabaseManager()
    with db.engine.connect() as conn:
        conn.execute(
            text("""
            CREATE TABLE IF NOT EXISTS market_breadth_history (
                date              DATE PRIMARY KEY,
                total             INT,
                advances          INT,
                declines          INT,
                unchanged         INT,
                near_52w_high     INT,
                near_52w_low      INT,
                pct_above_ema20   DOUBLE PRECISION,
                pct_above_ema50   DOUBLE PRECISION,
                pct_above_ema200  DOUBLE PRECISION,
                new_highs         INT,
                new_lows          INT,
                net_highs_lows    INT,
                created_at        TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        )
        conn.commit()
        print("Migration successful: market_breadth_history table ready.")


if __name__ == "__main__":
    run_migration()
