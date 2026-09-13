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


"""Daily pull: today's bhavcopy + deals + FII/DII. Cron it for ~19:30 IST.
    30 19 * * 1-5  cd /path/to/nse-screener && python daily.py >> cron.log 2>&1
"""
from datetime import date, timedelta

from ingest import bhavcopy, bulk_deals, corporate_actions, fii_dii


def main() -> None:
    d = date.today()
    # self-healing: also backfill the trailing week, so a slept-through
    # cron slot never leaves a hole in the panel
    for back in range(7, 0, -1):
        prev = d - timedelta(days=back)
        if prev.weekday() < 5:
            bhavcopy.store(prev)
    ok = bhavcopy.store(d)
    print(f"bhavcopy {d}: {'ok' if ok else 'not available yet (or holiday)'}")
    bulk_deals.store(d)
    fii_dii.store(d)
    # keep the CA file fresh: re-pull a trailing+leading window and merge
    corporate_actions.store(d - timedelta(days=30), d + timedelta(days=60))
    try:  # publish regime flips to the public status file (site reads it)
        from screener.paper_log import refresh_status

        refresh_status()
    except Exception as e:
        print(f"status refresh skipped: {e}")
    print("done")


if __name__ == "__main__":
    main()
