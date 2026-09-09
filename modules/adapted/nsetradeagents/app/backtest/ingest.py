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


import sqlite3
import time
from pathlib import Path

import pandas as pd
import structlog
from app.screener.universe import fetch_universe
from app.utils.market_data import extract_ticker_df, safe_yf_download

logger = structlog.get_logger()

_INDEX_TICKERS = ["^NSEI", "^INDIAVIX"]
_INGEST_START = "2021-01-01"
_INGEST_END = "2025-12-31"
_BATCH_SIZE = 40


def _ensure_schema(conn: sqlite3.Connection):
    """Create the bars table and its index if they don't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bars (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL NOT NULL,
            volume REAL,
            PRIMARY KEY (ticker, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bars_ticker_date ON bars (ticker, date)")
    conn.commit()


def _save_df(conn: sqlite3.Connection, ticker: str, df: pd.DataFrame) -> int:
    """Write one ticker's bars into the cache, skipping rows with no close.

    Returns the number of rows written.
    """
    if df is None or df.empty:
        return 0
    df = df.copy()
    df.index = pd.to_datetime(df.index).normalize()
    rows = []
    for dt, row in df.iterrows():
        close = row.get("Close")
        if close is None or pd.isna(close):
            continue
        rows.append(
            (
                ticker,
                dt.date().isoformat(),
                float(row.get("Open", close) or close),
                float(row.get("High", close) or close),
                float(row.get("Low", close) or close),
                float(close),
                float(row.get("Volume", 0) or 0),
            )
        )
    if rows:
        conn.executemany(
            "INSERT OR REPLACE INTO bars (ticker, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    return len(rows)


def run_ingest(db_path: str = "backtest_data.db", force: bool = False):
    """Download the full history the backtest needs into a local SQLite cache.

    Fetches the indices first, then the universe in batches. Skips entirely
    if the database already exists unless `force` is set. This is slow and
    meant to run once.
    """
    if not force and Path(db_path).exists():
        logger.info("ingest_skip_existing", db_path=db_path)
        return

    logger.info("ingest_start", start=_INGEST_START, end=_INGEST_END)
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)

    for ticker in _INDEX_TICKERS:
        logger.info("ingest_index", ticker=ticker)
        df = safe_yf_download(ticker, start=_INGEST_START, end=_INGEST_END)
        extracted = extract_ticker_df(df, ticker)
        if extracted is not None:
            df = extracted
        n = _save_df(conn, ticker, df)
        logger.info("ingest_index_done", ticker=ticker, rows=n)

    tickers = fetch_universe()
    logger.info("ingest_universe_start", total=len(tickers))

    total_rows = 0
    for i in range(0, len(tickers), _BATCH_SIZE):
        batch = tickers[i : i + _BATCH_SIZE]
        logger.info("ingest_batch", offset=i, size=len(batch))
        try:
            raw = safe_yf_download(batch, start=_INGEST_START, end=_INGEST_END)
            for ticker in batch:
                extracted = extract_ticker_df(raw, ticker)
                if extracted is None or extracted.empty:
                    logger.warning("ingest_no_data", ticker=ticker)
                    continue
                n = _save_df(conn, ticker, extracted)
                total_rows += n
        except Exception as e:
            logger.exception("ingest_batch_failed", offset=i, error=str(e))
        time.sleep(0.5)
    logger.info("ingest_complete", total_rows=total_rows)
    conn.close()
