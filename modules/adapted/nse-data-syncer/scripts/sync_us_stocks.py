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


"""
Sync daily OHLCV data for US large-cap stocks (S&P 500 universe) into
us_stocks + us_daily_prices tables.

Runs incrementally: only fetches from the last synced date onward.
First run triggers a full backfill from 2009-01-01.
"""
import os
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from sqlalchemy import text

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(base_dir, "web", ".env"))
sys.path.append(base_dir)

from app.database import DatabaseManager

BACKFILL_START = "2009-01-01"  # warmup for 1Y lookback before 2010 backtest start
BATCH_SIZE = 50  # tickers per yfinance batch download
DATA_DIR = os.path.join(base_dir, "data")


def get_russell1000_tickers() -> tuple[list[str], dict, dict]:
    """Read the latest Russell-1000-*.csv from the data/ directory."""
    csvs = sorted(
        [f for f in os.listdir(DATA_DIR) if f.startswith("Russell-1000-") and f.endswith(".csv")], reverse=True
    )

    if not csvs:
        msg = f"No Russell-1000-*.csv found in {DATA_DIR}"
        raise FileNotFoundError(msg)

    path = os.path.join(DATA_DIR, csvs[0])
    print(f"Using ticker list: {csvs[0]}")

    df = pd.read_csv(path)
    # Keep only equity rows, drop any non-stock rows
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"] == "Equity"]

    # Some ETF/index CSVs use non-standard ticker formats that yfinance doesn't recognise
    TICKER_REMAP = {"BRKB": "BRK-B", "BFA": "BF-A", "BFB": "BF-B", "LENB": "LEN-B", "UHALB": "UHAL"}
    tickers = [TICKER_REMAP.get(t, t) for t in df["Ticker"].str.strip().str.replace(".", "-", regex=False).tolist()]
    names = dict(zip(tickers, df["Name"].str.strip() if "Name" in df.columns else [""] * len(tickers), strict=False))
    sectors = dict(
        zip(tickers, df["Sector"].str.strip() if "Sector" in df.columns else [""] * len(tickers), strict=False)
    )

    print(f"Loaded {len(tickers)} Russell 1000 tickers.")
    return tickers, names, sectors


def ensure_tables(session):
    session.execute(
        text("""
        CREATE TABLE IF NOT EXISTS us_stocks (
            id       SERIAL PRIMARY KEY,
            ticker   VARCHAR(20) UNIQUE NOT NULL,
            name     VARCHAR(255),
            sector   VARCHAR(100),
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    )
    session.execute(
        text("""
        CREATE TABLE IF NOT EXISTS us_daily_prices (
            id           SERIAL PRIMARY KEY,
            us_stock_id  INTEGER NOT NULL REFERENCES us_stocks(id) ON DELETE CASCADE,
            date         DATE NOT NULL,
            open_price   DOUBLE PRECISION,
            high_price   DOUBLE PRECISION,
            low_price    DOUBLE PRECISION,
            close_price  DOUBLE PRECISION,
            volume       BIGINT,
            UNIQUE (us_stock_id, date)
        )
    """)
    )
    session.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_us_daily_prices_stock_date
            ON us_daily_prices (us_stock_id, date DESC)
    """)
    )
    session.execute(
        text("""
        CREATE INDEX IF NOT EXISTS ix_us_daily_prices_date
            ON us_daily_prices (date)
    """)
    )
    session.execute(
        text("""
        CREATE TABLE IF NOT EXISTS us_performance (
            id           SERIAL PRIMARY KEY,
            us_stock_id  INTEGER UNIQUE NOT NULL REFERENCES us_stocks(id) ON DELETE CASCADE,
            change_1w    DOUBLE PRECISION,
            change_1m    DOUBLE PRECISION,
            change_3m    DOUBLE PRECISION,
            change_6m    DOUBLE PRECISION,
            change_1y    DOUBLE PRECISION,
            change_3y    DOUBLE PRECISION,
            change_5y    DOUBLE PRECISION,
            updated_at   TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    )
    session.commit()
    print("Tables ensured.")


def upsert_stocks(session, tickers: list[str], names: dict, sectors: dict) -> dict:
    """Insert new tickers, return {ticker: id} map."""
    for ticker in tickers:
        session.execute(
            text("""
            INSERT INTO us_stocks (ticker, name, sector)
            VALUES (:t, :n, :s)
            ON CONFLICT (ticker) DO UPDATE
                SET name   = EXCLUDED.name,
                    sector = EXCLUDED.sector
        """),
            {"t": ticker, "n": names.get(ticker), "s": sectors.get(ticker)},
        )
    session.commit()

    rows = session.execute(text("SELECT id, ticker FROM us_stocks")).fetchall()
    return {r.ticker: r.id for r in rows}


def get_last_dates(session) -> dict:
    """Return {us_stock_id: last_date} for all stocks that have price data."""
    rows = session.execute(
        text("""
        SELECT us_stock_id, MAX(date) AS last_date
        FROM us_daily_prices
        GROUP BY us_stock_id
    """)
    ).fetchall()
    return {r.us_stock_id: r.last_date for r in rows}


def download_and_insert(session, batch_tickers: list[str], ticker_id_map: dict, last_dates: dict):
    if not batch_tickers:
        return

    # Determine earliest start date for this batch
    starts = []
    for t in batch_tickers:
        sid = ticker_id_map.get(t)
        last = last_dates.get(sid) if sid else None
        if last:
            starts.append(last + timedelta(days=1))
        else:
            starts.append(datetime.strptime(BACKFILL_START, "%Y-%m-%d").date())

    batch_start = min(starts)
    today = date.today()

    if batch_start > today:
        return  # All already up to date

    batch_start_str = batch_start.strftime("%Y-%m-%d")
    today_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")  # yfinance end is exclusive

    print(f"  Downloading {len(batch_tickers)} tickers from {batch_start_str}...")
    try:
        raw = yf.download(
            batch_tickers,
            start=batch_start_str,
            end=today_str,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as e:
        print(f"  yfinance error: {e}")
        return

    if raw.empty:
        print("  No data returned.")
        return

    def df_to_records(df, sid, per_start):
        df = df.dropna(subset=["Close"])
        if df.empty:
            return []
        out = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        out.index = (
            pd.to_datetime(out.index).tz_convert(None) if out.index.tz is not None else pd.to_datetime(out.index)
        )
        if per_start:
            out = out[out.index >= pd.Timestamp(per_start + timedelta(days=1))]
        if out.empty:
            return []
        out["us_stock_id"] = sid
        out["date"] = out.index.date
        out["open_price"] = pd.to_numeric(out["Open"], errors="coerce")
        out["high_price"] = pd.to_numeric(out["High"], errors="coerce")
        out["low_price"] = pd.to_numeric(out["Low"], errors="coerce")
        out["close_price"] = pd.to_numeric(out["Close"], errors="coerce")
        out["volume"] = pd.to_numeric(out["Volume"], errors="coerce").astype("Int64")
        out = out.dropna(subset=["close_price"])
        result = out[["us_stock_id", "date", "open_price", "high_price", "low_price", "close_price", "volume"]].to_dict(
            "records"
        )
        for r in result:
            for k in ("open_price", "high_price", "low_price", "close_price"):
                if pd.isna(r[k]):
                    r[k] = None
            if pd.isna(r["volume"]):
                r["volume"] = None
            else:
                r["volume"] = int(r["volume"])
        return result

    # yfinance returns MultiIndex columns when multiple tickers
    if isinstance(raw.columns, pd.MultiIndex):
        # columns: (field, ticker)
        records = []
        for ticker in batch_tickers:
            try:
                df = raw.xs(ticker, axis=1, level=1)
            except KeyError:
                continue
            sid = ticker_id_map.get(ticker)
            if not sid:
                continue
            records.extend(df_to_records(df, sid, last_dates.get(sid)))
    else:
        # Single ticker
        ticker = batch_tickers[0]
        sid = ticker_id_map.get(ticker)
        if not sid:
            return
        records = df_to_records(raw, sid, last_dates.get(sid))

    if not records:
        return

    values = [
        (r["us_stock_id"], r["date"], r["open_price"], r["high_price"], r["low_price"], r["close_price"], r["volume"])
        for r in records
    ]
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
            values,
            page_size=2000,
        )
        raw_conn.commit()
        cursor.close()
    except Exception:
        raw_conn.rollback()
        raise
    finally:
        raw_conn.close()
    print(f"  Inserted/updated {len(records)} price records.")


def compute_performance(session, us_stock_id: int):
    rows = session.execute(
        text("""
        SELECT date, close_price FROM us_daily_prices
        WHERE us_stock_id = :id AND close_price IS NOT NULL
        ORDER BY date DESC LIMIT 2000
    """),
        {"id": us_stock_id},
    ).fetchall()
    if not rows:
        return

    df = pd.DataFrame(rows, columns=["date", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    latest_price = df.iloc[-1]["close"]
    latest_date = df.iloc[-1]["date"]

    def pct(days):
        cutoff = latest_date - timedelta(days=days)
        ref = df[df["date"] <= cutoff]
        if ref.empty:
            return None
        ref_price = ref.iloc[-1]["close"]
        return float(round((latest_price - ref_price) / ref_price * 100, 2)) if ref_price else None

    session.execute(
        text("""
        INSERT INTO us_performance
            (us_stock_id, change_1w, change_1m, change_3m, change_6m, change_1y, change_3y, change_5y, updated_at)
        VALUES
            (:id, :w, :m1, :m3, :m6, :y1, :y3, :y5, NOW())
        ON CONFLICT (us_stock_id) DO UPDATE SET
            change_1w  = :w,
            change_1m  = :m1,
            change_3m  = :m3,
            change_6m  = :m6,
            change_1y  = :y1,
            change_3y  = :y3,
            change_5y  = :y5,
            updated_at = NOW()
    """),
        {
            "id": us_stock_id,
            "w": pct(7),
            "m1": pct(30),
            "m3": pct(90),
            "m6": pct(180),
            "y1": pct(365),
            "y3": pct(365 * 3),
            "y5": pct(365 * 5),
        },
    )
    session.commit()


def main():
    print("=== US Stocks Daily Sync ===")
    db = DatabaseManager()
    session = db.Session()

    try:
        ensure_tables(session)
        tickers, names, sectors = get_russell1000_tickers()
        ticker_id_map = upsert_stocks(session, tickers, names, sectors)
        last_dates = get_last_dates(session)

        # Process in batches
        for i in range(0, len(tickers), BATCH_SIZE):
            batch = tickers[i : i + BATCH_SIZE]
            print(f"Batch {i // BATCH_SIZE + 1}/{(len(tickers) - 1) // BATCH_SIZE + 1}")
            download_and_insert(session, batch, ticker_id_map, last_dates)
            time.sleep(0.5)  # gentle rate limiting

        # Summary
        total = session.execute(text("SELECT COUNT(*) FROM us_daily_prices")).scalar()
        stocks = session.execute(text("SELECT COUNT(*) FROM us_stocks")).scalar()
        print(f"\nSync complete. {stocks} stocks, {total:,} total price records.")

        # Compute performance metrics for all stocks
        print("\nComputing performance metrics...")
        for i, sid in enumerate(ticker_id_map.values(), start=1):
            compute_performance(session, sid)
            if i % 200 == 0:
                print(f"  Processed {i}/{len(ticker_id_map)}...")
        print(f"Performance metrics updated for {len(ticker_id_map)} stocks.")

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
