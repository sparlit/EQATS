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


"""Infer historical circuit limits from stock prices using NSE price-band rules.

NSE Price Band Rules (approximate):
  - Price < ₹100   → 20% band
  - ₹100 ≤ Price < ₹200 → 10% band
  - ₹200 ≤ Price     → 5% band (default)
  - IPO stocks: 20% for first 5 trading days (not handled here)
  - Stocks under ASM/GSM: may have 2% or 5% band (not handled here)

Reads all NSE normalized delivery parquets, computes inferred circuit limits,
and stores them in stock_circuit_limits with source='inferred'.

Usage:
    python scripts/infer_historical_circuits.py               # last 1 year
    python scripts/infer_historical_circuits.py --days 30     # last 30 days
    python scripts/infer_historical_circuits.py --from 2026-01-01 --to 2026-09-07
"""


import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config.connections import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

NSE_DELIVERY_DIR = Path("data/normalized/delivery/NSE")


def infer_filter_pct(prev_close: float) -> float:
    """Infer circuit filter percentage from prev_close using NSE rules."""
    if prev_close <= 0:
        return 5.0
    if prev_close < 100:
        return 20.0
    if prev_close < 200:
        return 10.0
    return 5.0


def infer_circuit_limits(prev_close: float) -> tuple[float, float]:
    """Compute upper and lower circuit limits from prev_close."""
    if prev_close <= 0:
        return 0.0, 0.0
    pct = infer_filter_pct(prev_close)
    upper = round(prev_close * (1 + pct / 100), 2)
    lower = round(prev_close * (1 - pct / 100), 2)
    return upper, lower


def process_stock(delivery_path: Path, start_date: date, end_date: date) -> list[dict]:
    """Process a single stock's delivery parquet and infer circuit limits."""
    try:
        df = pd.read_parquet(delivery_path)
    except Exception:
        return []

    if "date" not in df.columns or "close" not in df.columns:
        return []

    df["date"] = pd.to_datetime(df["date"]).dt.date
    symbol = delivery_path.stem

    # Filter date range
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    if df.empty:
        return []

    df = df.sort_values("date").reset_index(drop=True)

    records = []
    for _i, row in df.iterrows():
        prev_close = float(row["close"])
        upper, lower = infer_circuit_limits(prev_close)
        filter_pct = infer_filter_pct(prev_close)

        records.append(
            {
                "symbol": symbol,
                "exchange": "NSE",
                "trade_date": row["date"],
                "prev_close": prev_close,
                "upper_circuit": upper,
                "lower_circuit": lower,
                "filter_pct": filter_pct,
                "source": "inferred",
            }
        )

    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Infer historical circuit limits")
    parser.add_argument("--days", type=int, default=365, help="Look back N days")
    parser.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--batch", type=int, default=500, help="DB batch size")
    args = parser.parse_args()

    engine = get_engine()

    if args.from_date:
        start_date = date.fromisoformat(args.from_date)
    else:
        start_date = date.today() - timedelta(days=args.days)

    end_date = date.fromisoformat(args.to_date) if args.to_date else date.today()

    log.info(f"Infer circuit limits: {start_date} to {end_date}")

    # Find all NSE delivery parquets
    parquets = sorted(NSE_DELIVERY_DIR.glob("*.parquet"))
    log.info(f"Found {len(parquets)} stock parquets")

    total_records = 0
    batch_records = []

    for i, pq in enumerate(parquets):
        records = process_stock(pq, start_date, end_date)
        batch_records.extend(records)

        if len(batch_records) >= args.batch:
            upsert_batch(engine, batch_records)
            total_records += len(batch_records)
            batch_records = []

        if (i + 1) % 500 == 0:
            log.info(f"  Processed {i + 1}/{len(parquets)} stocks, {total_records} records")

    # Final batch
    if batch_records:
        upsert_batch(engine, batch_records)
        total_records += len(batch_records)

    log.info(f"Done: {total_records} inferred circuit limit records")
    return 0


def upsert_batch(engine, records: list[dict]) -> None:
    """Upsert a batch of circuit limit records."""
    if not records:
        return
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


if __name__ == "__main__":
    raise SystemExit(main())
