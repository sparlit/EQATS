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


"""One-time repair pass for us_daily_prices gaps discovered on 2026-07-10.

Two known causes, both fixed by the same logic:

1. A handful of currently-tracked tickers (e.g. AAPL, MSFT) only have a
   few months of history instead of the full 2009+ backfill, because
   sync_us_stocks.py's bulk 50-ticker yf.download() calls can silently
   truncate individual tickers within a batch (confirmed: fetching these
   tickers individually, or even replaying their exact original batch,
   returns full history fine - it was a one-off flaky response never
   re-validated since the daily sync is purely incremental).
2. 217 of the 1,218 us_stocks rows are orphaned - present in the DB from
   whatever ticker list was used for the initial 2026-06-16 bootstrap,
   but absent from the single Russell-1000 CSV actually committed to
   git, so the daily sync's ticker loop never touches them again. Most
   are genuinely delisted/renamed (ATVI, SPLK, PARA, SQ...); a handful
   (SHOP, JBLU, WPP, UPST, ...) are still perfectly fetchable and just
   never got a successful sync before falling off the list.

For every stock whose earliest stored date is missing or suspiciously
late (> 2009-06-01), this fetches that ticker *individually* (not
batched - batching is what caused the original truncation) for the
full range up to just before its current earliest date (or through
today, if it has zero rows), and upserts whatever comes back. This is
naturally a no-op for genuine recent IPOs/spinoffs (yfinance correctly
returns nothing before their real listing date) and for truly-delisted
orphans (yfinance errors, nothing to insert) - only real gaps get
backfilled.

Does NOT re-add orphaned tickers to the daily sync's ticker loop (that
loop is driven by the committed CSV, reflecting current Russell 1000
membership) - this script only backfills their historical data as it
stands today. Run once, not part of the daily GitHub Action.
"""
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))
sys.path.append(base_dir)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import DatabaseManager
from sync_us_stocks import BACKFILL_START, compute_performance

CANDIDATE_CUTOFF = "2009-06-01"  # stocks with real history starting on/before this are skipped


def get_candidates(session):
    rows = session.execute(
        text("""
        SELECT s.id, s.ticker, t.first_date
        FROM us_stocks s
        LEFT JOIN (
            SELECT us_stock_id, MIN(date) AS first_date
            FROM us_daily_prices GROUP BY us_stock_id
        ) t ON t.us_stock_id = s.id
        WHERE t.first_date IS NULL OR t.first_date > :cutoff
        ORDER BY s.ticker
    """),
        {"cutoff": CANDIDATE_CUTOFF},
    ).fetchall()
    return [(r.id, r.ticker, r.first_date) for r in rows]


def fetch_individual(ticker: str, start: str, end: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False, threads=False)
    except Exception:
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Close"])
    if df.empty:
        return pd.DataFrame()
    return df


def upsert_rows(session, us_stock_id: int, df: pd.DataFrame) -> int:
    records = []
    for idx, row in df.iterrows():
        records.append(
            (
                us_stock_id,
                idx.date(),
                float(row["Open"]) if pd.notna(row["Open"]) else None,
                float(row["High"]) if pd.notna(row["High"]) else None,
                float(row["Low"]) if pd.notna(row["Low"]) else None,
                float(row["Close"]) if pd.notna(row["Close"]) else None,
                int(row["Volume"]) if pd.notna(row["Volume"]) else None,
            )
        )
    if not records:
        return 0

    raw_conn = session.bind.raw_connection()
    try:
        cursor = raw_conn.cursor()
        execute_values(
            cursor,
            """
            INSERT INTO us_daily_prices
                (us_stock_id, date, open_price, high_price, low_price, close_price, volume)
            VALUES %s
            ON CONFLICT (us_stock_id, date) DO UPDATE
                SET open_price  = EXCLUDED.open_price,
                    high_price  = EXCLUDED.high_price,
                    low_price   = EXCLUDED.low_price,
                    close_price = EXCLUDED.close_price,
                    volume      = EXCLUDED.volume
        """,
            records,
            page_size=2000,
        )
        raw_conn.commit()
        cursor.close()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    return len(records)


def main():
    print("=== US History Repair ===")
    db = DatabaseManager()
    session = db.Session()

    try:
        candidates = get_candidates(session)
        print(f"Found {len(candidates)} candidate tickers to check.")

        repaired = 0
        rows_added = 0
        still_empty = []

        for i, (sid, ticker, first_date) in enumerate(candidates, start=1):
            end_date = (first_date - timedelta(days=1)) if first_date else datetime.now().date()
            end_str = (end_date + timedelta(days=1)).strftime("%Y-%m-%d")  # yfinance end is exclusive

            if end_date < datetime.strptime(BACKFILL_START, "%Y-%m-%d").date():
                continue  # nothing earlier to fetch

            df = fetch_individual(ticker, BACKFILL_START, end_str)
            n = upsert_rows(session, sid, df)

            if n:
                compute_performance(session, sid)
                repaired += 1
                rows_added += n
                print(
                    f"  [{i}/{len(candidates)}] {ticker}: +{n} rows "
                    f"({df.index.min().date()} -> {df.index.max().date()})"
                )
            else:
                still_empty.append(ticker)

            if i % 50 == 0:
                print(f"  ... progress {i}/{len(candidates)}")
            time.sleep(0.3)  # gentle rate limiting

        print(f"\nDone. Repaired {repaired} tickers, added {rows_added:,} rows.")
        print(
            f"{len(still_empty)} tickers still have no earlier data available "
            f"(genuinely delisted/renamed or real recent listing date)."
        )
        if still_empty:
            print("  " + ", ".join(still_empty))

    except Exception as e:
        session.rollback()
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
