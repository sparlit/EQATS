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


"""One-time and repeatable quality audit for the existing NSE SQLite database."""


import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_PRICE_COLUMNS = {
    "symbol",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover_lacs",
    "delivery_pct",
}


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def audit_database(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        msg = f"Database not found: {db_path}"
        raise FileNotFoundError(msg)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    report: dict[str, Any] = {
        "database": str(db_path),
        "audited_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": "PASS",
        "errors": [],
        "warnings": [],
        "metrics": {},
    }

    try:
        integrity = scalar(conn, "PRAGMA integrity_check")
        report["metrics"]["integrity_check"] = integrity
        if integrity != "ok":
            report["errors"].append(f"SQLite integrity check failed: {integrity}")

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        report["metrics"]["tables"] = sorted(tables)
        if "daily_prices" not in tables:
            report["errors"].append("Required table daily_prices is missing")
            return report

        columns = table_columns(conn, "daily_prices")
        missing_columns = sorted(REQUIRED_PRICE_COLUMNS - columns)
        report["metrics"]["daily_prices_columns"] = sorted(columns)
        if missing_columns:
            report["errors"].append("daily_prices missing columns: " + ", ".join(missing_columns))

        metrics = report["metrics"]
        metrics["row_count"] = scalar(conn, "SELECT COUNT(*) FROM daily_prices")
        metrics["symbol_count"] = scalar(conn, "SELECT COUNT(DISTINCT symbol) FROM daily_prices")
        metrics["session_count"] = scalar(conn, "SELECT COUNT(DISTINCT date) FROM daily_prices")
        metrics["oldest_date"] = scalar(conn, "SELECT MIN(date) FROM daily_prices")
        metrics["newest_date"] = scalar(conn, "SELECT MAX(date) FROM daily_prices")

        metrics["duplicate_symbol_dates"] = scalar(
            conn,
            """SELECT COUNT(*) FROM (
                SELECT symbol, date, COUNT(*) c
                FROM daily_prices GROUP BY symbol, date HAVING c > 1
            )""",
        )
        metrics["invalid_ohlc_rows"] = scalar(
            conn,
            """SELECT COUNT(*) FROM daily_prices
               WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
                  OR high < low OR high < open OR high < close
                  OR low > open OR low > close OR close <= 0""",
        )
        metrics["negative_volume_rows"] = scalar(conn, "SELECT COUNT(*) FROM daily_prices WHERE volume < 0")
        metrics["missing_turnover_rows"] = scalar(conn, "SELECT COUNT(*) FROM daily_prices WHERE turnover_lacs IS NULL")
        metrics["missing_delivery_rows"] = scalar(conn, "SELECT COUNT(*) FROM daily_prices WHERE delivery_pct IS NULL")
        metrics["invalid_delivery_rows"] = scalar(
            conn,
            "SELECT COUNT(*) FROM daily_prices WHERE delivery_pct < 0 OR delivery_pct > 100",
        )
        metrics["symbols_with_260_sessions"] = scalar(
            conn,
            """SELECT COUNT(*) FROM (
                SELECT symbol FROM daily_prices
                GROUP BY symbol HAVING COUNT(DISTINCT date) >= 260
            )""",
        )
        metrics["symbols_with_400_sessions"] = scalar(
            conn,
            """SELECT COUNT(*) FROM (
                SELECT symbol FROM daily_prices
                GROUP BY symbol HAVING COUNT(DISTINCT date) >= 400
            )""",
        )

        if metrics["session_count"] < 400:
            report["errors"].append(f"Only {metrics['session_count']} distinct sessions; V2 requires at least 400")
        if metrics["duplicate_symbol_dates"]:
            report["errors"].append("Duplicate symbol/date rows detected")
        if metrics["invalid_ohlc_rows"]:
            report["errors"].append("Invalid OHLC rows detected")
        if metrics["negative_volume_rows"]:
            report["errors"].append("Negative volume rows detected")
        if metrics["missing_turnover_rows"]:
            report["warnings"].append("Some rows have missing turnover")
        if metrics["missing_delivery_rows"]:
            report["warnings"].append("Some rows have missing delivery percentage")
        if metrics["invalid_delivery_rows"]:
            report["errors"].append("Delivery percentage outside 0-100 detected")

    finally:
        conn.close()

    if report["errors"]:
        report["status"] = "FAIL"
    elif report["warnings"]:
        report["status"] = "WARN"
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="nse_scanner.db")
    parser.add_argument("--output", default="output/nse_db_audit.json")
    args = parser.parse_args()

    report = audit_database(Path(args.db))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
