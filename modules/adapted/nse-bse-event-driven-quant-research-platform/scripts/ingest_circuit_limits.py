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


"""Ingest daily NSE Price Band / Circuit Breaker CSV from NSE archives.

URL pattern:
    https://nsearchives.nseindia.com/content/equities/circuit_breakers/PRICE_BAND_{YYYYMMDD}.csv

Also tries Upstox V2 snapshot as fallback.

Usage:
    python scripts/ingest_circuit_limits.py                  # today
    python scripts/ingest_circuit_limits.py --date 2026-09-05
    python scripts/ingest_circuit_limits.py --from 2026-08-01 --to 2026-09-07
"""


import argparse
import csv
import io
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config.connections import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

NSE_PRICE_BAND_URL = (
    "https://nsearchives.nseindia.com/content/equities/circuit_breakers/PRICE_BAND_{yyyymmdd}.csv"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def fetch_nse_price_band(trade_date: date, timeout: float = 30.0) -> list[dict] | None:
    """Fetch NSE Price Band CSV for a given date. Returns list of row dicts or None."""
    yyyymmdd = trade_date.strftime("%Y%m%d")
    url = NSE_PRICE_BAND_URL.format(yyyymmdd=yyyymmdd)
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        if resp.status_code in (404, 403):
            log.warning(f"NSE Price Band unavailable for {trade_date}: HTTP {resp.status_code}")
            return None
        resp.raise_for_status()
        text = resp.text
        if text.lstrip()[:1] == "<":
            log.warning(f"NSE Price Band blocked for {trade_date} (HTML response)")
            return None
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        log.info(f"NSE Price Band {trade_date}: {len(rows)} stocks")
        return rows
    except Exception as e:
        log.error(f"Error fetching NSE Price Band for {trade_date}: {e}")
        return None


def parse_nse_rows(rows: list[dict], trade_date: date) -> list[dict]:
    """Parse NSE Price Band CSV rows into circuit limit records."""
    records = []
    for row in rows:
        symbol = row.get("SYMBOL", "").strip()
        if not symbol:
            continue
        series = row.get("SERIES", "").strip()
        if series not in ("EQ", "BE", "BZ", "SM", "ST"):
            continue

        try:
            prev_close = float(row.get("PREV_CLOSE", 0) or 0)
            upper = float(row.get("UPPER_BAND", 0) or 0)
            lower = float(row.get("LOWER_BAND", 0) or 0)
            filter_pct = float(row.get("CIRCUIT_FILTER_PERCENTAGE", 0) or 0)
        except (ValueError, TypeError):
            continue

        if upper <= 0 and lower <= 0:
            continue

        records.append(
            {
                "symbol": symbol,
                "exchange": "NSE",
                "trade_date": trade_date,
                "prev_close": prev_close,
                "upper_circuit": upper,
                "lower_circuit": lower,
                "filter_pct": filter_pct,
                "source": "nse_archive",
            }
        )
    return records


def upsert_circuit_limits(engine, records: list[dict]) -> int:
    """Upsert circuit limit records into DB. Returns count inserted."""
    if not records:
        return 0
    with engine.begin() as conn:
        stmt = sa.text("""
            INSERT INTO stock_circuit_limits
                (symbol, exchange, trade_date, prev_close, upper_circuit, lower_circuit, filter_pct, source)
            VALUES (:symbol, :exchange, :trade_date, :prev_close, :upper_circuit, :lower_circuit, :filter_pct, :source)
            ON CONFLICT (symbol, exchange, trade_date, source) DO UPDATE SET
                prev_close = EXCLUDED.prev_close,
                upper_circuit = EXCLUDED.upper_circuit,
                lower_circuit = EXCLUDED.lower_circuit,
                filter_pct = EXCLUDED.filter_pct
        """)
        for rec in records:
            rec["trade_date"] = str(rec["trade_date"])
            conn.execute(stmt, rec)
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest NSE circuit limit data")
    parser.add_argument("--date", help="Single date (YYYY-MM-DD)")
    parser.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    engine = get_engine()

    if args.date:
        dates = [date.fromisoformat(args.date)]
    elif args.from_date:
        start = date.fromisoformat(args.from_date)
        end = date.fromisoformat(args.to_date) if args.to_date else date.today()
        dates = []
        d = start
        while d <= end:
            dates.append(d)
            d += timedelta(days=1)
    else:
        dates = [date.today()]

    total = 0
    for d in dates:
        rows = fetch_nse_price_band(d)
        if rows:
            records = parse_nse_rows(rows, d)
            n = upsert_circuit_limits(engine, records)
            total += n
            log.info(f"  {d}: {n} records upserted")
        else:
            log.info(f"  {d}: no data")

    log.info(f"Total: {total} circuit limit records ingested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
