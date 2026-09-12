import datetime
import sys

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    elif dt.tzinfo is None:
        now = ist.localize(dt)
    else:
        now = dt.astimezone(ist)
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


if __name__ == "__main__":
    sys.path.insert(0, "..")

    try:
        from upstox_data import get_ltp, get_spot, get_vix
    except ImportError:
        print("upstox_data module not found. Skipping spot price example.")
        sys.exit(0)

    # Full spot data (OHLC + prev close + change %)
    for symbol in ["NIFTY", "BANKNIFTY"]:
        spot = get_spot(symbol)
        if spot:
            print(f"\n{spot['symbol']}")
            print(f"  LTP:        {spot['ltp']:,.2f}")
            print(f"  Open:       {spot['open']:,.2f}")
            print(f"  High:       {spot['day_high']:,.2f}")
            print(f"  Low:        {spot['day_low']:,.2f}")
            print(f"  Prev Close: {spot['prev_close']:,.2f}")
            print(f"  Change:     {spot['change_pct']:+.2f}%")
        else:
            print(f"\n{symbol}: no data (market may be closed)")

    # Lightweight LTP only
    print(f"\nNIFTY LTP: {get_ltp('NIFTY')}")
    print(f"India VIX: {get_vix()}")
