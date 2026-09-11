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


"""Backfill bhavcopy history.

    python backfill.py --days 420                       # trailing window
    python backfill.py --start 2016-01-01 --end 2019-12-31

Dates before 2020 come from the legacy cm*bhav archive (no delivery data);
2020+ from sec_bhavdata_full. Existing files are skipped without sleeping,
so re-running over a covered range is cheap.
"""
import argparse
import time
from datetime import date, timedelta

from ingest import bhavcopy, bhavcopy_old

import config

FULL_FORMAT_FROM = date(2020, 1, 1)


def main(start: date, end: date) -> None:
    d, got = start, 0
    while d <= end:
        if d.weekday() < 5:  # skip weekends outright
            out = config.DATA_DIR / "bhav" / f"{d.isoformat()}.parquet"
            if not out.exists():
                mod = bhavcopy if d >= FULL_FORMAT_FROM else bhavcopy_old
                try:
                    if mod.store(d):
                        got += 1
                        if got % 20 == 0:
                            print(f"{got} days done, at {d}")
                    time.sleep(config.SLEEP_SECS)
                except Exception as e:
                    print(f"{d}: {e} — continuing")
        d += timedelta(days=1)
    print(f"Backfill complete: {got} new trading days stored.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--start", type=date.fromisoformat)
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    a = p.parse_args()
    if not a.days and not a.start:
        p.error("give --days or --start")
    main(a.start or date.today() - timedelta(days=a.days), a.end)
