import datetime
from data_fetcher import (
    fetch_and_store, detect_and_store_holidays, DEFAULT_SYMBOLS
)
from scoring2 import generate_suggestions
from models import init_db, get_session, DailyPrice


def main():
    # Ensure DB and tables exist
    init_db(db_version='2.0')

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
    date_rows = session.query(DailyPrice.date).filter(
        DailyPrice.date >= cutoff_date
    ).distinct().order_by(DailyPrice.date.asc()).all()
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

    print('Top suggestions for the last 60 days:')
    for sym, score, reason in top:
        print(f'{sym}: Score={score:.4f} | {reason}')

if __name__ == '__main__':
    main()
