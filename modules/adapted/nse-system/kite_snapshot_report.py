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


"""Read-only coverage and quality report for KITE market snapshots."""

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from config import DB_PATH

METRIC_COLUMNS = (
    "last_price",
    "market_cap_cr",
    "pe",
    "debt_to_equity",
    "dividend_yield",
    "free_cash_flow",
    "profit_growth_yoy",
    "revenue_growth_yoy",
    "roe",
    "volume",
)


def report(database, as_of=None):
    path = Path(database).resolve()
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "kite_market_snapshots" not in tables:
            raise RuntimeError("No KITE snapshot table exists in this database")
        dates = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT as_of_date FROM kite_market_snapshots ORDER BY as_of_date"
            )
        ]
        if not dates:
            raise RuntimeError("The KITE snapshot table is empty")
        selected_date = as_of or dates[-1]
        if selected_date not in dates:
            raise ValueError(
                f"No KITE snapshot found for {selected_date}; available dates: {', '.join(dates)}"
            )

        rows = conn.execute(
            "SELECT symbol, data_quality_flags FROM kite_market_snapshots WHERE as_of_date=?",
            (selected_date,),
        ).fetchall()
        total = len(rows)
        mapped = sum(bool(row[0]) for row in rows)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(kite_market_snapshots)")}
        print(f"KITE market snapshot: {selected_date} ({total} instruments)")
        print(f"Symbol mapped: {mapped}/{total}; unresolved: {total - mapped}")
        print("Financial-period end and public filing timestamp: not supplied")
        present_metrics = [name for name in METRIC_COLUMNS if name in columns]
        provenance_columns = (
            "source_file",
            "source_sha256",
            "source_modified_at",
            "security_master_file",
            "security_master_sha256",
            "imported_at",
        )
        if all(name in columns for name in provenance_columns):
            provenance = conn.execute(
                "SELECT DISTINCT "
                + ",".join(provenance_columns)
                + " FROM kite_market_snapshots WHERE as_of_date=?",
                (selected_date,),
            ).fetchall()
            for artifact in provenance:
                print(
                    "Source artifact: "
                    f"{artifact[0]} (SHA-256 {artifact[1]}, "
                    f"modified {artifact[2]}, imported {artifact[5]})"
                )
                print(f"Security master: {artifact[3]} (SHA-256 {artifact[4]})")
            print(
                "File modification time is host metadata, not proof of "
                "market-observation or publication time."
            )
        selected = ",".join(f"count({name})" for name in present_metrics)
        counts = conn.execute(
            f"SELECT {selected} FROM kite_market_snapshots WHERE as_of_date=?", (selected_date,)
        ).fetchone()
        print("\nStructured field coverage")
        for name, count in zip(present_metrics, counts, strict=False):
            print(f"  {name}: {count}/{total}")

        flags = Counter()
        for _, payload in rows:
            try:
                flags.update(json.loads(payload or "[]"))
            except json.JSONDecodeError as exc:
                raise ValueError("Malformed data_quality_flags JSON in KITE snapshot") from exc
        print("\nQuality flags (row counts)")
        if flags:
            for flag, count in sorted(flags.items()):
                print(f"  {flag}: {count}")
        else:
            print("  none")

        if "market_data_attestations" in tables:
            attestations = conn.execute(
                "SELECT field, agreed, action, COUNT(*) "
                "FROM market_data_attestations WHERE as_of_date=? "
                "GROUP BY field, agreed, action ORDER BY field, agreed, action",
                (selected_date,),
            ).fetchall()
            if attestations:
                print("\nKITE/ScanX field attestations")
                for field, agreed, action, count in attestations:
                    verdict = "agreed" if agreed else "withheld"
                    print(f"  {field}: {verdict} / {action}: {count}")
        print(
            "\nRaw snapshots remain preserved. Only values explicitly "
            "corroborated against same-date ScanX data are promoted; "
            "undated financial metrics are not historical replay data."
        )
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB_PATH), help="SQLite database (opened read-only)")
    parser.add_argument("--as-of", help="Snapshot date YYYY-MM-DD")
    args = parser.parse_args(argv)
    report(args.db, args.as_of)


if __name__ == "__main__":
    main()
