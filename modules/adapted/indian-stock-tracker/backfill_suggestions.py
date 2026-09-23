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
Backfill script: Generate suggestions for all historical dates that have
substantial price data (at least 20 stocks).

This script ensures that the Suggestion table is populated for all dates
that the user might want to filter by. After running once, subsequent
cron runs of run_daily.py will add suggestions for new dates automatically.
"""
import sys

from models import DailyPrice, Suggestion, get_session
from scoring2 import generate_suggestions
from sqlalchemy import func

# Minimum number of stocks needed for a date to be considered "substantial"
MIN_STOCKS_PER_DATE = 20


def backfill_suggestions():
    session = get_session()
    try:
        # Find all dates that have substantial price data
        dates_with_data = (
            session.query(DailyPrice.date, func.count(DailyPrice.id).label("cnt"))
            .group_by(DailyPrice.date)
            .having(func.count(DailyPrice.id) >= MIN_STOCKS_PER_DATE)
            .order_by(DailyPrice.date.desc())
            .all()
        )

        print(f"Found {len(dates_with_data)} dates with substantial price data")

        total_generated = 0
        for i, (date, count) in enumerate(dates_with_data):
            # Check if suggestions already exist for this date
            existing_count = session.query(Suggestion).filter_by(date=date).count()
            if existing_count == 0:
                print(f"[{i + 1}/{len(dates_with_data)}] Generating suggestions for {date} ({count} prices)...")
                try:
                    result = generate_suggestions(date)
                    total_generated += 1
                    print(f"  → Generated {len(result)} suggestions for {date}")
                except Exception as e:
                    print(f"  → Error generating for {date}: {e}")
            else:
                print(f"[{i + 1}/{len(dates_with_data)}] Skipping {date} (already has {existing_count} suggestions)")

        print(f"\nBackfill complete. Generated suggestions for {total_generated} new dates.")

        # Summary
        total_suggestions = session.query(Suggestion).count()
        distinct_dates = session.query(Suggestion.date).distinct().count()
        print(f"Database now has {total_suggestions} suggestions across {distinct_dates} distinct dates")
    finally:
        session.close()


if __name__ == "__main__":
    backfill_suggestions()
