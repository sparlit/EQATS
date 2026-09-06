"""Sync major US market indices into the indices / index_daily_prices / index_performance tables.
Runs daily after US market close (same workflow as sync_us_stocks.py).
"""
import sys, os
import pandas as pd
import yfinance as yf
from sqlalchemy import text
from datetime import datetime, timedelta
from dotenv import load_dotenv
from psycopg2.extras import execute_values

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, 'web', '.env'))
sys.path.append(base_dir)
from app.database import DatabaseManager

US_INDICES = [
    ('^GSPC',  'S&P 500'),
    ('^IXIC',  'Nasdaq Composite'),
    ('^DJI',   'Dow Jones Industrial Average'),
    ('^RUT',   'Russell 2000'),
    ('^RUI',   'Russell 1000'),
    ('^VIX',   'CBOE Volatility Index'),
]

HISTORY_START = '2018-01-01'


def upsert_index(session, symbol, name) -> int:
    row = session.execute(
        text("SELECT id FROM indices WHERE symbol = :s"), {'s': symbol}
    ).fetchone()
    if row:
        return row[0]
    row = session.execute(
        text("""
            INSERT INTO indices (symbol, name, is_active, created_at, updated_at)
            VALUES (:s, :n, 1, NOW(), NOW())
            RETURNING id
        """),
        {'s': symbol, 'n': name}
    ).fetchone()
    session.commit()
    return row[0]


def sync_prices(session, index_id: int, symbol: str) -> int:
    raw = yf.download(symbol, start=HISTORY_START, progress=False, auto_adjust=True, threads=False)
    if raw.empty:
        print(f"  {symbol}: no data from yfinance")
        return 0

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index()
    raw.columns = [c.lower() for c in raw.columns]

    dates = pd.to_datetime(raw['date'])
    if dates.dt.tz is not None:
        dates = dates.dt.tz_convert(None)
    raw['date'] = dates

    records = []
    for _, row in raw.iterrows():
        records.append((
            index_id,
            row['date'].strftime('%Y-%m-%d'),
            float(row.get('open') or 0) or None,
            float(row.get('high') or 0) or None,
            float(row.get('low')  or 0) or None,
            float(row.get('close') or 0) or None,
            int(row.get('volume') or 0) or None,
        ))

    raw_conn = session.bind.raw_connection()
    try:
        cursor = raw_conn.cursor()
        execute_values(cursor, """
            INSERT INTO index_daily_prices
                (index_id, date, open_price, high_price, low_price, close_price, volume)
            VALUES %s
            ON CONFLICT (index_id, date) DO UPDATE SET
                open_price  = EXCLUDED.open_price,
                high_price  = EXCLUDED.high_price,
                low_price   = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                volume      = EXCLUDED.volume
        """, records, page_size=500)
        raw_conn.commit()
        cursor.close()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()

    return len(records)


def compute_performance(session, index_id: int):
    rows = session.execute(
        text("""
            SELECT date, close_price FROM index_daily_prices
            WHERE index_id = :id AND close_price IS NOT NULL
            ORDER BY date DESC LIMIT 2000
        """),
        {'id': index_id}
    ).fetchall()
    if not rows:
        return

    df = pd.DataFrame(rows, columns=['date', 'close'])
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    latest_price = df.iloc[-1]['close']
    latest_date  = df.iloc[-1]['date']

    def pct(days):
        cutoff = latest_date - timedelta(days=days)
        ref = df[df['date'] <= cutoff]
        if ref.empty:
            return None
        ref_price = ref.iloc[-1]['close']
        return float(round((latest_price - ref_price) / ref_price * 100, 2)) if ref_price else None

    session.execute(text("""
        INSERT INTO index_performance
            (index_id, change_1w, change_1m, change_3m, change_6m, change_1y, change_3y, change_5y, updated_at)
        VALUES
            (:id, :w, :m1, :m3, :m6, :y1, :y3, :y5, NOW())
        ON CONFLICT (index_id) DO UPDATE SET
            change_1w  = :w,
            change_1m  = :m1,
            change_3m  = :m3,
            change_6m  = :m6,
            change_1y  = :y1,
            change_3y  = :y3,
            change_5y  = :y5,
            updated_at = NOW()
    """), {
        'id': index_id,
        'w':  pct(7),
        'm1': pct(30),
        'm3': pct(90),
        'm6': pct(180),
        'y1': pct(365),
        'y3': pct(365 * 3),
        'y5': pct(365 * 5),
    })
    session.commit()


def main():
    print("=== Syncing US Market Indices ===")
    db = DatabaseManager()
    session = db.Session()
    try:
        for symbol, name in US_INDICES:
            print(f"\n{symbol} ({name})")
            index_id = upsert_index(session, symbol, name)
            n = sync_prices(session, index_id, symbol)
            print(f"  Upserted {n} daily price rows")
            compute_performance(session, index_id)
            row = session.execute(
                text("SELECT change_1w, change_1m, change_1y FROM index_performance WHERE index_id = :id"),
                {'id': index_id}
            ).fetchone()
            if row:
                print(f"  Perf: 1W={row[0]}%  1M={row[1]}%  1Y={row[2]}%")
        print("\nDone.")
    finally:
        session.close()


if __name__ == '__main__':
    main()
