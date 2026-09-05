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

import config
from ingest import bhavcopy, bhavcopy_old

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
    p.add_argument("--start", type=lambda s: date.fromisoformat(s))
    p.add_argument("--end", type=lambda s: date.fromisoformat(s),
                   default=date.today())
    a = p.parse_args()
    if not a.days and not a.start:
        p.error("give --days or --start")
    main(a.start or date.today() - timedelta(days=a.days), a.end)
