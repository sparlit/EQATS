from __future__ import annotations

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


"""Official NSE daily index snapshot ingestion for Scanner V2.

The production source is the NSE Daily Snapshot CSV named
``ind_close_all_DDMMYYYY.csv``. Network retrieval is retry-safe and the parser
is independently testable with local CSV bytes.
"""

import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

DEFAULT_URL_TEMPLATE = "https://archives.nseindia.com/content/indices/ind_close_all_{date}.csv"

INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS index_perf (
    index_name TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL NOT NULL,
    change_pct REAL,
    volume REAL,
    pe REAL,
    pb REAL,
    div_yield REAL,
    source_file TEXT NOT NULL,
    source_type TEXT NOT NULL,
    loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    quality_status TEXT NOT NULL,
    PRIMARY KEY(index_name, date)
);
CREATE INDEX IF NOT EXISTS idx_index_perf_date ON index_perf(date);
"""


@dataclass(frozen=True)
class IndexIngestionResult:
    trade_date: str
    source_file: str
    downloaded: bool
    rows_parsed: int
    rows_upserted: int
    snapshot_path: str | None
    attempts: int


def snapshot_filename(trade_date: date | str) -> str:
    value = pd.Timestamp(trade_date).date()
    return f"ind_close_all_{value.strftime('%d%m%Y')}.csv"


def _column(frame: pd.DataFrame, *aliases: str) -> str | None:
    normalized = {str(c).strip().upper().replace(" ", "_"): c for c in frame.columns}
    for alias in aliases:
        key = alias.strip().upper().replace(" ", "_")
        if key in normalized:
            return normalized[key]
    return None


def parse_index_snapshot(content: bytes, expected_date: date | str | None = None) -> pd.DataFrame:
    raw = pd.read_csv(BytesIO(content))
    name_col = _column(raw, "INDEX_NAME", "INDEX", "Index Name")
    date_col = _column(raw, "INDEX_DATE", "DATE", "HistoricalDate", "Index Date")
    close_col = _column(raw, "CLOSING_INDEX_VALUE", "CLOSE", "Closing Index Value")
    open_col = _column(raw, "OPEN_INDEX_VALUE", "OPEN", "Open Index Value")
    high_col = _column(raw, "HIGH_INDEX_VALUE", "HIGH", "High Index Value")
    low_col = _column(raw, "LOW_INDEX_VALUE", "LOW", "Low Index Value")
    change_col = _column(raw, "PERCENT_CHANGE", "CHANGE_%", "Change(%)")

    if not name_col or not date_col or not close_col:
        msg = "NSE index snapshot missing required name/date/close columns"
        raise ValueError(msg)

    frame = pd.DataFrame(
        {
            "index_name": raw[name_col].astype(str).str.strip(),
            "date": pd.to_datetime(raw[date_col], dayfirst=True, errors="coerce").dt.date.astype("string"),
            "open": pd.to_numeric(raw[open_col], errors="coerce") if open_col else pd.NA,
            "high": pd.to_numeric(raw[high_col], errors="coerce") if high_col else pd.NA,
            "low": pd.to_numeric(raw[low_col], errors="coerce") if low_col else pd.NA,
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
            "change_pct": pd.to_numeric(raw[change_col], errors="coerce") if change_col else pd.NA,
        }
    )
    frame = frame.dropna(subset=["index_name", "date", "close"])
    frame = frame[frame["index_name"].ne("")].drop_duplicates(["index_name", "date"], keep="last")

    if expected_date is not None:
        expected = pd.Timestamp(expected_date).date().isoformat()
        actual = set(frame["date"].astype(str))
        if actual != {expected}:
            msg = f"snapshot date mismatch: expected {expected}, found {sorted(actual)}"
            raise ValueError(msg)
    if frame.empty:
        msg = "NSE index snapshot contained no valid rows"
        raise ValueError(msg)
    return frame.reset_index(drop=True)


def download_snapshot(
    trade_date: date | str,
    *,
    url_template: str = DEFAULT_URL_TEMPLATE,
    attempts: int = 3,
    timeout_seconds: int = 30,
    backoff_seconds: float = 2.0,
    session: requests.Session | None = None,
) -> tuple[bytes, int]:
    filename = snapshot_filename(trade_date)
    url = url_template.format(date=pd.Timestamp(trade_date).strftime("%d%m%Y"), filename=filename)
    client = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NSE-Scanner-V2/1.0)",
        "Accept": "text/csv,*/*",
        "Referer": "https://www.nseindia.com/all-reports",
    }
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            if not response.content or b"," not in response.content[:500]:
                msg = "downloaded NSE snapshot is not a CSV payload"
                raise ValueError(msg)
            return response.content, attempt
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)
    msg = f"NSE index snapshot download failed after {attempts} attempts: {last_error}"
    raise RuntimeError(msg)


def upsert_index_perf(db_path: str | Path, frame: pd.DataFrame, source_file: str) -> int:
    rows = []
    for row in frame.to_dict("records"):
        rows.append(
            (
                row["index_name"],
                str(row["date"]),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row["close"],
                row.get("change_pct"),
                source_file,
                "NSE_DAILY_SNAPSHOT",
                "VALIDATED",
            )
        )
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(INDEX_SCHEMA)
        conn.executemany(
            """INSERT INTO index_perf
               (index_name,date,open,high,low,close,change_pct,source_file,source_type,quality_status)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(index_name,date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low,
                 close=excluded.close, change_pct=excluded.change_pct,
                 source_file=excluded.source_file, source_type=excluded.source_type,
                 loaded_at=CURRENT_TIMESTAMP, quality_status=excluded.quality_status""",
            rows,
        )
    return len(rows)


def ingest_daily_index_snapshot(
    db_path: str | Path,
    trade_date: date | str,
    *,
    snapshot_dir: str | Path = "market_data/index_snapshots",
    url_template: str = DEFAULT_URL_TEMPLATE,
    content: bytes | None = None,
) -> IndexIngestionResult:
    filename = snapshot_filename(trade_date)
    attempts = 0
    downloaded = content is None
    if content is None:
        content, attempts = download_snapshot(trade_date, url_template=url_template)
    frame = parse_index_snapshot(content, expected_date=trade_date)
    destination = Path(snapshot_dir) / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    upserted = upsert_index_perf(db_path, frame, filename)
    return IndexIngestionResult(
        trade_date=pd.Timestamp(trade_date).date().isoformat(),
        source_file=filename,
        downloaded=downloaded,
        rows_parsed=len(frame),
        rows_upserted=upserted,
        snapshot_path=str(destination),
        attempts=attempts,
    )
