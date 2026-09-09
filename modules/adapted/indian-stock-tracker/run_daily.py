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


import datetime

from data_fetcher import DEFAULT_SYMBOLS, detect_and_store_holidays, fetch_and_store
from models import DailyPrice, get_session, init_db
from scoring2 import generate_suggestions


def main():
    # Ensure DB and tables exist
    init_db(db_version="2.0")

    # Define symbols to track (default list of ~50 NSE stocks)
    symbols = DEFAULT_SYMBOLS

    # Step 1: Fetch latest market data
    fetch_and_store(symbols)

    # Step 2: Detect any missing weekday/holiday slots in the 60-day window
    # and insert placeholder rows so the date range stays continuous.
    detect_and_store_holidays(symbols, days_back=60)

    # Step 3: Generate suggestions for each date in the 60-day window
    session = get_session()
    # Get all distinct dates from the last 60 days
    cutoff_date = datetime.date.today() - datetime.timedelta(days=60)
    date_rows = (
        session.query(DailyPrice.date)
        .filter(DailyPrice.date >= cutoff_date)
        .distinct()
        .order_by(DailyPrice.date.asc())
        .all()
    )
    session.close()

    # Collect top suggestions from each day
    all_suggestions = []
    for date_row in date_rows:
        target_date = date_row[0]  # Extract date from tuple
        top = generate_suggestions(target_date=target_date)
        all_suggestions.extend(top)

    # Sort by score descending and take top N
    all_suggestions.sort(key=lambda x: x[1], reverse=True)
    top = all_suggestions[:50]

    print("Top suggestions for the last 60 days:")
    for sym, score, reason in top:
        print(f"{sym}: Score={score:.4f} | {reason}")


if __name__ == "__main__":
    main()
