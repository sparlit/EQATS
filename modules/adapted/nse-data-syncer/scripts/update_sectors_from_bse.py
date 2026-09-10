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


#!/usr/bin/env python3
"""
Update sector / industry fields for all stocks using data/Equity_List.csv (BSE).

Mapping:
    Sector Name      → sector
    Industry New Name → subsector1
    Igroup Name       → subsector2
    ISubgroup Name    → subsector3  (also written to subsector for backwards compat)
    Industry          → industry

Join key: ISIN No ↔ stocks.isin  (falls back to Security Id ↔ stocks.bse_symbol)

Usage:
    python scripts/update_sectors_from_bse.py
"""

import csv
import logging
import os
import sys
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

_script_dir = os.path.dirname(os.path.abspath(__file__))
for _candidate in [
    os.path.join(_script_dir, "..", "web", ".env"),
    os.path.join(_script_dir, "..", ".env"),
]:
    if os.path.exists(_candidate):
        load_dotenv(_candidate)
        break

CSV_PATH = os.path.join(_script_dir, "..", "data", "Equity_List.csv")


def connect():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        msg = "DATABASE_URL not set"
        raise RuntimeError(msg)
    p = urlparse(db_url)
    return psycopg2.connect(
        host=p.hostname,
        port=p.port or 5432,
        database=p.path.lstrip("/"),
        user=p.username,
        password=p.password,
        sslmode="require",
    )


def load_csv():
    rows = {}  # isin → dict
    bse_rows = {}  # bse_symbol → dict
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            isin = row.get("ISIN No", "").strip()
            bse_sym = row.get("Security Id", "").strip()
            data = {
                "sector": row.get("Sector Name", "").strip(),
                "subsector1": row.get("Industry New Name", "").strip(),
                "subsector2": row.get("Igroup Name", "").strip(),
                "subsector3": row.get("ISubgroup Name", "").strip(),
                "industry": row.get("Industry", "").strip(),
            }
            # Use ISubgroup Name as the primary subsector (most specific)
            data["subsector"] = data["subsector3"] or data["subsector2"]

            if isin:
                rows[isin] = data
            if bse_sym:
                bse_rows[bse_sym] = data
    logger.info(f"Loaded {len(rows)} ISIN rows and {len(bse_rows)} BSE symbol rows from CSV")
    return rows, bse_rows


def main():
    isin_map, bse_map = load_csv()

    conn = connect()
    cur = conn.cursor()

    cur.execute("SELECT id, isin, bse_symbol FROM stocks WHERE is_active = true OR is_active IS NULL")
    stocks = cur.fetchall()
    logger.info(f"Found {len(stocks)} stocks in DB")

    updated = 0
    not_found = 0

    for stock_id, isin, bse_symbol in stocks:
        data = None
        if isin and isin in isin_map:
            data = isin_map[isin]
        elif bse_symbol and bse_symbol in bse_map:
            data = bse_map[bse_symbol]

        if not data:
            not_found += 1
            continue

        cur.execute(
            """
            UPDATE stocks SET
                sector    = %s,
                subsector = %s,
                subsector1 = %s,
                subsector2 = %s,
                subsector3 = %s,
                industry  = %s
            WHERE id = %s
            """,
            (
                data["sector"] or None,
                data["subsector"] or None,
                data["subsector1"] or None,
                data["subsector2"] or None,
                data["subsector3"] or None,
                data["industry"] or None,
                stock_id,
            ),
        )
        updated += 1

    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"Updated {updated} stocks")
    logger.info(f"Not found in CSV: {not_found} stocks")


if __name__ == "__main__":
    main()
