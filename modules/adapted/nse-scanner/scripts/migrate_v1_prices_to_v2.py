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


"""Additive migration of validated V1 daily_prices rows into daily_prices_v2."""


import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

MIGRATION_ID = "001_data_foundation"


def apply_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(sql)
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    conn.execute(
        """INSERT OR REPLACE INTO schema_migrations
           (migration_id, applied_at, checksum, notes)
           VALUES (?, CURRENT_TIMESTAMP, ?, ?)""",
        (MIGRATION_ID, checksum, "Applied by migrate_v1_prices_to_v2.py"),
    )


def migrate(db_path: Path, schema_path: Path, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        apply_schema(conn, schema_path)

        source_rows = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
        source_range = conn.execute("SELECT MIN(date), MAX(date) FROM daily_prices").fetchone()
        invalid_rows = conn.execute(
            """SELECT COUNT(*) FROM daily_prices
               WHERE symbol IS NULL OR TRIM(symbol) = '' OR date IS NULL
                  OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR high < low OR high < open OR high < close
                  OR low > open OR low > close OR close <= 0
                  OR volume < 0
                  OR delivery_pct < 0 OR delivery_pct > 100"""
        ).fetchone()[0]

        if invalid_rows:
            msg = f"Migration blocked: {invalid_rows} invalid daily_prices rows. Run audit first."
            raise ValueError(msg)

        if not dry_run:
            conn.execute(
                """INSERT INTO daily_prices_v2 (
                    symbol, trade_date, prev_close, open, high, low, last_price,
                    close, avg_price, volume, turnover_lacs, trades,
                    delivery_qty, delivery_pct, source, source_loaded_at,
                    quality_status
                )
                SELECT
                    TRIM(symbol), date, prev_close, open, high, low, last_price,
                    close, avg_price, volume, turnover_lacs, trades,
                    delivery_qty, delivery_pct, 'NSE_V1_MIGRATION',
                    CURRENT_TIMESTAMP,
                    CASE
                        WHEN turnover_lacs IS NULL OR delivery_pct IS NULL
                        THEN 'PARTIAL'
                        ELSE 'VALID'
                    END
                FROM daily_prices
                WHERE 1 = 1
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                    prev_close=excluded.prev_close,
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    last_price=excluded.last_price,
                    close=excluded.close,
                    avg_price=excluded.avg_price,
                    volume=excluded.volume,
                    turnover_lacs=excluded.turnover_lacs,
                    trades=excluded.trades,
                    delivery_qty=excluded.delivery_qty,
                    delivery_pct=excluded.delivery_pct,
                    source=excluded.source,
                    source_loaded_at=excluded.source_loaded_at,
                    quality_status=excluded.quality_status"""
            )

        target_rows = conn.execute("SELECT COUNT(*) FROM daily_prices_v2").fetchone()[0]
        target_range = conn.execute("SELECT MIN(trade_date), MAX(trade_date) FROM daily_prices_v2").fetchone()
        status = "DRY_RUN" if dry_run else ("PASS" if source_rows == target_rows else "WARN")
        details = {
            "migration_id": MIGRATION_ID,
            "source_rows": source_rows,
            "target_rows": target_rows,
            "source_range": source_range,
            "target_range": target_range,
            "invalid_rows": invalid_rows,
            "status": status,
        }

        if not dry_run:
            conn.execute(
                """INSERT INTO migration_reconciliation (
                    migration_id, source_table, target_table,
                    source_rows, target_rows,
                    source_min_date, source_max_date,
                    target_min_date, target_max_date,
                    duplicate_rows, invalid_rows, status, details_json
                ) VALUES (?, 'daily_prices', 'daily_prices_v2', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
                (
                    MIGRATION_ID,
                    source_rows,
                    target_rows,
                    source_range[0],
                    source_range[1],
                    target_range[0],
                    target_range[1],
                    invalid_rows,
                    status,
                    json.dumps(details),
                ),
            )
            conn.commit()
        else:
            conn.rollback()
        return details
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--schema", default="migrations/v2/001_data_foundation.sql")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = migrate(Path(args.db), Path(args.schema), dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
