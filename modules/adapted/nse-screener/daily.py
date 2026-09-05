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
