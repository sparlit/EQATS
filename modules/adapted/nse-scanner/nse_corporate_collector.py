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


"""NSE-only universe, market-cap and surveillance collection.

Collectors fail closed per dataset: a failed download never deletes the last
valid point-in-time snapshot. Normalized snapshots are Git-backed separately.
"""

import hashlib
import io
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from nse_historical_downloader import HEADERS, date_vars, day_folder
from v2.corporate_data import calculated_market_cap_cr
from v2.database import V2Database

EQUITY_MASTER_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
RAW_ROOT = Path("corporate_data/raw")


@dataclass
class DatasetHealth:
    dataset: str
    status: str
    rows: int = 0
    source: str = ""
    error: str = ""


def _column(frame: pd.DataFrame, *names: str) -> str:
    normalized = {str(c).strip().upper().replace(" ", "_"): c for c in frame.columns}
    for name in names:
        key = name.strip().upper().replace(" ", "_")
        if key in normalized:
            return normalized[key]
    msg = f"none of the required columns found: {names}"
    raise ValueError(msg)


def _download_table(url: str, dataset: str, timeout: int = 30) -> tuple[pd.DataFrame, Path]:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    if len(response.content) < 100:
        msg = f"{dataset} response is unexpectedly small"
        raise ValueError(msg)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(response.content).hexdigest()[:12]
    content_type = response.headers.get("content-type", "").lower()
    excel = (
        url.lower().split("?")[0].endswith((".xls", ".xlsx"))
        or "spreadsheet" in content_type
        or response.content[:2] == b"PK"
    )
    suffix = ".xlsx" if excel else ".csv"
    path = RAW_ROOT / dataset / f"{stamp}_{digest}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    frame = pd.read_excel(io.BytesIO(response.content)) if excel else pd.read_csv(io.BytesIO(response.content))
    return frame, path


def ingest_equity_master(conn: sqlite3.Connection, frame: pd.DataFrame) -> int:
    symbol = _column(frame, "SYMBOL")
    company = _column(frame, "NAME OF COMPANY", "COMPANY_NAME")
    series = _column(frame, "SERIES")
    isin = _column(frame, "ISIN NUMBER", "ISIN")
    listing = _column(frame, "DATE OF LISTING", "LISTING_DATE")
    rows = []
    for row in frame.itertuples(index=False, name=None):
        values = dict(zip(frame.columns, row, strict=False))
        rows.append(
            (
                str(values[symbol]).strip().upper(),
                str(values[isin]).strip(),
                str(values[company]).strip(),
                str(values[series]).strip().upper(),
                str(values[listing]).strip(),
                1,
            )
        )
    conn.executemany(
        """INSERT INTO symbol_master_v2
      (symbol,isin,company_name,series,listing_date,active) VALUES (?,?,?,?,?,?)
      ON CONFLICT(symbol) DO UPDATE SET isin=excluded.isin,company_name=excluded.company_name,
      series=excluded.series,listing_date=excluded.listing_date,active=1,
      updated_at=CURRENT_TIMESTAMP""",
        rows,
    )
    symbols = [row[0] for row in rows]
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        conn.execute(f"UPDATE symbol_master_v2 SET active=0 WHERE symbol NOT IN ({placeholders})", symbols)
    return len(rows)


def ingest_market_caps(conn: sqlite3.Connection, frame: pd.DataFrame, available_date: str) -> int:
    symbol = _column(frame, "SYMBOL", "SECURITY SYMBOL")
    cap = _column(frame, "MARKET CAP (RS. CR)", "MARKET_CAP_CR", "MARKET CAPITALISATION (CR.)")
    as_of = next((c for c in frame.columns if str(c).strip().upper().replace(" ", "_") in {"AS_OF_DATE", "DATE"}), None)
    rows = []
    for _, item in frame.iterrows():
        value = pd.to_numeric(item[cap], errors="coerce")
        if pd.isna(value) or float(value) <= 0:
            continue
        period = str(item[as_of]) if as_of else available_date
        rows.append((str(item[symbol]).strip().upper(), period, available_date, float(value), "NSE_DIRECT_MARKET_CAP"))
    conn.executemany(
        """INSERT INTO market_cap_snapshots_v3
      (symbol,as_of_date,available_date,market_cap_cr,source) VALUES (?,?,?,?,?)
      ON CONFLICT(symbol,as_of_date,source) DO UPDATE SET
      available_date=excluded.available_date,market_cap_cr=excluded.market_cap_cr""",
        rows,
    )
    return len(rows)


def calculate_caps_from_shares(conn: sqlite3.Connection, trade_date: str) -> int:
    price_table = (
        "daily_prices_v2"
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_prices_v2'").fetchone()
        else "daily_prices"
    )
    date_col = "trade_date" if price_table == "daily_prices_v2" else "date"
    rows = conn.execute(
        f"""SELECT p.symbol,p.close,s.shares_outstanding,s.as_of_date,s.available_date,p.{date_col},s.filing_id
      FROM {price_table} p JOIN shares_outstanding_v3 s ON s.symbol=p.symbol
      WHERE p.{date_col}=(SELECT MAX(p2.{date_col}) FROM {price_table} p2
                         WHERE p2.symbol=p.symbol AND p2.{date_col}<=?)
      AND s.available_date<=? AND s.available_date=(
       SELECT MAX(s2.available_date) FROM shares_outstanding_v3 s2
       WHERE s2.symbol=s.symbol AND s2.available_date<=?)""",
        (trade_date, trade_date, trade_date),
    ).fetchall()
    values = [
        (
            r[0],
            str(r[5]),
            str(r[5]),
            calculated_market_cap_cr(float(r[1]), float(r[2])),
            "CALCULATED_QUARTERLY_SHARES",
            r[6],
        )
        for r in rows
    ]
    conn.executemany(
        """INSERT INTO market_cap_snapshots_v3
      (symbol,as_of_date,available_date,market_cap_cr,source,filing_id) VALUES (?,?,?,?,?,?)
      ON CONFLICT(symbol,as_of_date,source) DO UPDATE SET market_cap_cr=excluded.market_cap_cr,
      available_date=excluded.available_date,filing_id=excluded.filing_id""",
        values,
    )
    return len(values)


def rebuild_caps_from_shares(
    conn: sqlite3.Connection, start_date: str | None = None, end_date: str | None = None
) -> int:
    """Build retained-session caps using only shares known by each close date."""
    price_table = (
        "daily_prices_v2"
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_prices_v2'").fetchone()
        else "daily_prices"
    )
    date_col = "trade_date" if price_table == "daily_prices_v2" else "date"
    conditions = ["s.available_date <= p." + date_col, "p.close > 0", "s.shares_outstanding > 0"]
    params: list[str] = []
    if start_date:
        conditions.append(f"p.{date_col} >= ?")
        params.append(start_date)
    if end_date:
        conditions.append(f"p.{date_col} <= ?")
        params.append(end_date)
    rows = conn.execute(
        f"""SELECT p.symbol,p.{date_col},p.close,s.shares_outstanding,s.filing_id
      FROM {price_table} p JOIN shares_outstanding_v3 s ON s.symbol=p.symbol
      WHERE {" AND ".join(conditions)} AND s.available_date=(
        SELECT MAX(s2.available_date) FROM shares_outstanding_v3 s2
        WHERE s2.symbol=p.symbol AND s2.available_date<=p.{date_col})""",
        params,
    ).fetchall()
    values = [
        (
            r[0],
            str(r[1]),
            str(r[1]),
            calculated_market_cap_cr(float(r[2]), float(r[3])),
            "CALCULATED_QUARTERLY_SHARES",
            r[4],
        )
        for r in rows
    ]
    conn.executemany(
        """INSERT INTO market_cap_snapshots_v3
      (symbol,as_of_date,available_date,market_cap_cr,source,filing_id) VALUES (?,?,?,?,?,?)
      ON CONFLICT(symbol,as_of_date,source) DO UPDATE SET market_cap_cr=excluded.market_cap_cr,
      available_date=excluded.available_date,filing_id=excluded.filing_id""",
        values,
    )
    return len(values)


def ingest_surveillance(conn: sqlite3.Connection, trade_date: str) -> int:
    folder, fmt = Path(day_folder(date.fromisoformat(trade_date))), date_vars(date.fromisoformat(trade_date))
    paths = [folder / f"REG_IND{fmt['DDMMYY']}.csv", folder / f"REG1_IND{fmt['DDMMYYYY']}.csv"]
    count = 0
    for path in paths:
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        try:
            symbol = _column(frame, "SYMBOL", "SECURITY")
        except ValueError:
            continue
        reason_col = next(
            (c for c in frame.columns if any(k in str(c).upper() for k in ("REASON", "INDICATOR", "SURVEILLANCE"))),
            None,
        )
        rows = [
            (
                str(row[symbol]).strip().upper(),
                trade_date,
                "NSE_SURVEILLANCE",
                str(row[reason_col]) if reason_col else path.stem,
                "NSE",
                1,
            )
            for _, row in frame.iterrows()
        ]
        conn.executemany(
            """INSERT INTO regulatory_restrictions_v2
          (symbol,trade_date,restriction_type,reason,source,active) VALUES (?,?,?,?,?,?)
          ON CONFLICT(symbol,trade_date,restriction_type) DO UPDATE SET reason=excluded.reason,active=1""",
            rows,
        )
        count += len(rows)
    return count


def refresh_current_market_cap(conn: sqlite3.Connection, trade_date: str) -> int:
    rows = conn.execute(
        """SELECT symbol,market_cap_cr,as_of_date,source FROM (
      SELECT m.symbol,m.market_cap_cr,m.as_of_date,m.source,
        ROW_NUMBER() OVER (PARTITION BY m.symbol ORDER BY m.available_date DESC,
          CASE WHEN m.source='NSE_DIRECT_MARKET_CAP' THEN 0 ELSE 1 END, m.as_of_date DESC) AS ranked
      FROM market_cap_snapshots_v3 m WHERE m.available_date<=?) WHERE ranked=1""",
        (trade_date,),
    ).fetchall()
    conn.executemany(
        """UPDATE symbol_master_v2 SET market_cap_cr=?,market_cap_as_of=?,market_cap_source=?,updated_at=CURRENT_TIMESTAMP WHERE symbol=?""",
        [(r[1], r[2], r[3], r[0]) for r in rows],
    )
    return len(rows)


def run_collection(db_path: str, trade_date: str, market_cap_url: str | None = None) -> dict:
    V2Database(db_path).ensure_v3_schema()
    health: list[DatasetHealth] = []
    try:
        frame, raw = _download_table(os.getenv("NSE_EQUITY_MASTER_URL", EQUITY_MASTER_URL), "equity_master")
        with sqlite3.connect(db_path) as conn:
            rows = ingest_equity_master(conn, frame)
        health.append(DatasetHealth("equity_master", "FRESH", rows, str(raw)))
    except Exception as exc:
        health.append(DatasetHealth("equity_master", "REUSED_LAST_VALID", error=str(exc)))
    cap_url = market_cap_url or os.getenv("NSE_MARKET_CAP_URL", "").strip()
    if cap_url:
        try:
            frame, raw = _download_table(cap_url, "market_cap")
            with sqlite3.connect(db_path) as conn:
                rows = ingest_market_caps(conn, frame, trade_date)
            health.append(DatasetHealth("market_cap", "FRESH", rows, str(raw)))
        except Exception as exc:
            health.append(DatasetHealth("market_cap", "REUSED_LAST_VALID", error=str(exc)))
    else:
        health.append(DatasetHealth("market_cap", "NOT_CONFIGURED", error="NSE_MARKET_CAP_URL is not set"))
    # Incremental shareholding collection has its own Git-backed filing history.
    # A listing failure intentionally leaves the restored normalized snapshot intact.
    try:
        from nse_shareholding_collector import collect as collect_shareholding

        shareholding = collect_shareholding(
            db_path=db_path,
            as_of=date.fromisoformat(trade_date),
            days=int(os.getenv("NSE_SHAREHOLDING_WINDOW_DAYS", "7")),
            csv_fallback=Path(
                os.getenv("NSE_SHAREHOLDING_CSV_FALLBACK", "manual_import/raw/nse_shareholding_20260401_20260817.csv")
            ),
        )
        health.append(
            DatasetHealth(
                "shareholding",
                shareholding.status,
                shareholding.normalized,
                error=shareholding.error or (f"rejected={shareholding.rejected}" if shareholding.rejected else ""),
            )
        )
    except Exception as exc:
        health.append(DatasetHealth("shareholding", "REUSED_LAST_VALID", error=str(exc)))
    try:
        from nse_corporate_actions_collector import collect as collect_actions

        actions = collect_actions(
            db_path, date.fromisoformat(trade_date), days=int(os.getenv("NSE_CORPORATE_ACTION_WINDOW_DAYS", "7"))
        )
        health.append(DatasetHealth("corporate_actions", actions.status, actions.normalized, error=actions.error))
    except Exception as exc:
        health.append(DatasetHealth("corporate_actions", "REUSED_LAST_VALID", error=str(exc)))
    with sqlite3.connect(db_path) as conn:
        calculated = calculate_caps_from_shares(conn, trade_date)
        restricted = ingest_surveillance(conn, trade_date)
        current = refresh_current_market_cap(conn, trade_date)
        conn.executemany(
            """INSERT INTO corporate_dataset_health_v3
          (dataset,as_of_date,status,row_count,detail) VALUES (?,?,?,?,?)
          ON CONFLICT(dataset,as_of_date) DO UPDATE SET status=excluded.status,
          row_count=excluded.row_count,detail=excluded.detail,checked_at=CURRENT_TIMESTAMP""",
            [(item.dataset, trade_date, item.status, item.rows, item.error) for item in health],
        )
    health.extend(
        [
            DatasetHealth("calculated_market_cap", "FRESH" if calculated else "NO_SHARES_AVAILABLE", calculated),
            DatasetHealth("surveillance", "FRESH" if restricted else "NO_FILE", restricted),
            DatasetHealth("current_market_cap", "FRESH" if current else "NO_VALID_SNAPSHOT", current),
        ]
    )
    payload = {
        "run_at": datetime.now(UTC).isoformat(),
        "trade_date": trade_date,
        "status": "READY" if current else "DEGRADED",
        "datasets": [asdict(item) for item in health],
    }
    output = Path("output/nse_corporate_health.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
