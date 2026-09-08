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


import argparse
from datetime import date, timedelta

from models import Asset, Suggestion, get_session
from scoring2 import generate_suggestions


def list_suggestions(target_date: date, asset_type: str | None = None):
    session = get_session()
    query = session.query(Suggestion, Asset).join(Asset, Suggestion.asset_id == Asset.id)
    query = query.filter(Suggestion.date == target_date)
    if asset_type:
        query = query.filter(Asset.type == asset_type)
    suggestions = query.order_by(Suggestion.score.desc()).all()
    if not suggestions:
        print(f"No suggestions found for {target_date}. Generating now...")
        top = generate_suggestions(target_date)
        if not top:
            print(
                f"No scorable price data available for {target_date} "
                f"(prices may be missing OHLC values). Try a different date "
                f"or re-run the daily fetch."
            )
        for sym, score, reason in top:
            print(f"{sym}: Score={score:.4f} | {reason}")
    else:
        for sug, asset in suggestions:
            print(f"{asset.symbol}: Score={sug.score:.4f} | {sug.reasoning}")
    session.close()


def main():
    parser = argparse.ArgumentParser(description="Indian Stock Tracker CLI")
    parser.add_argument("--date", type=str, help="Date for suggestions in dd-mm-yyyy (default: yesterday)")
    parser.add_argument(
        "--type",
        type=str,
        choices=["equity", "mutual_fund", "bond", "derivative", "commodity"],
        help="Filter suggestions by asset type",
    )
    args = parser.parse_args()
    if args.date:
        try:
            # Try parsing as dd-mm-yyyy format
            day, month, year = map(int, args.date.split("-"))
            target = date(year, month, day)
        except ValueError:
            print("Invalid date format. Use dd-mm-yyyy")
            return
    else:
        target = date.today() - timedelta(days=1)

    list_suggestions(target, args.type)


if __name__ == "__main__":
    main()
