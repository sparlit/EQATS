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


"""Read-only coverage and data-quality report for imported ScanX snapshots."""
import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

import db

GROUPS = {
    "Long-term quality": (
        "roe_avg_3y",
        "roe_avg_10y",
        "roa_avg_3y",
        "roa_avg_5y",
        "opm_avg_5y",
        "opm_avg_10y",
        "roce_growth_5y",
        "roe_growth_5y",
    ),
    "Earnings growth": (
        "quarter_sales_yoy_growth",
        "quarter_profit_yoy_growth",
        "annual_revenue_growth",
        "sales_growth_qoq",
        "profit_growth_qoq",
    ),
    "Cash flow and balance sheet": (
        "free_cash_flow",
        "profit_after_tax",
        "net_change_in_cash",
        "change_in_working_capital",
        "current_assets",
        "current_liabilities",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "inventory",
        "capex_growth",
    ),
    "Valuation and peers": (
        "ev_ebitda",
        "pe_sector_ratio",
        "market_cap_sales",
        "industry_pe",
        "industry_pb",
        "industry_dividend_yield",
    ),
    "Ownership": (
        "dii_holding_change",
        "fii_holding_change",
        "public_holding",
        "promoter_holding_change",
    ),
}


def report(database, as_of=None):
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "scanx_fundamentals_snapshots" not in tables:
            msg = "No ScanX snapshot table exists in this database"
            raise RuntimeError(msg)
        dates = [
            row[0]
            for row in conn.execute("SELECT DISTINCT as_of_date FROM scanx_fundamentals_snapshots ORDER BY as_of_date")
        ]
        if not dates:
            msg = "The ScanX snapshot table is empty"
            raise RuntimeError(msg)
        selected_date = as_of or dates[-1]
        if selected_date not in dates:
            msg = f"No ScanX snapshot found for {selected_date}; available dates: {', '.join(dates)}"
            raise ValueError(msg)
        row_count = conn.execute(
            "SELECT count(*) FROM scanx_fundamentals_snapshots WHERE as_of_date=?", (selected_date,)
        ).fetchone()[0]
        cols = {row[1] for row in conn.execute("PRAGMA table_info(scanx_fundamentals_snapshots)")}
        print(f"ScanX export snapshot: {selected_date} ({row_count} rows)")
        print("Underlying financial-period end / publication date: not supplied")
        provenance_columns = (
            "source_file",
            "source_sha256",
            "source_modified_at",
            "security_master_file",
            "security_master_sha256",
            "imported_at",
        )
        if all(name in cols for name in provenance_columns):
            provenance = conn.execute(
                "SELECT DISTINCT "
                + ",".join(provenance_columns)
                + " FROM scanx_fundamentals_snapshots WHERE as_of_date=?",
                (selected_date,),
            ).fetchall()
            for artifact in provenance:
                print(
                    "Source artifact: "
                    f"{artifact[0]} (SHA-256 {artifact[1]}, "
                    f"modified {artifact[2]}, imported {artifact[5]})"
                )
                print(f"Security master: {artifact[3]} (SHA-256 {artifact[4]})")
            print("File modification time is host metadata, not proof of market-observation or publication time.")
        for group, fields in GROUPS.items():
            present = [field for field in fields if field in cols]
            if not present:
                continue
            select = ",".join(f"count({field})" for field in present)
            counts = conn.execute(
                f"SELECT {select} FROM scanx_fundamentals_snapshots WHERE as_of_date=?", (selected_date,)
            ).fetchone()
            print(f"\n{group}")
            for field, count in zip(present, counts, strict=False):
                print(f"  {field}: {count}/{row_count}")

        flags = Counter()
        for (payload,) in conn.execute(
            "SELECT data_quality_flags FROM scanx_fundamentals_snapshots WHERE as_of_date=?", (selected_date,)
        ):
            try:
                flags.update(json.loads(payload or "[]"))
            except json.JSONDecodeError as exc:
                msg = "Malformed data_quality_flags JSON in snapshot"
                raise ValueError(msg) from exc
        print("\nQuality flags (row counts)")
        if flags:
            for flag, count in sorted(flags.items()):
                print(f"  {flag}: {count}")
        else:
            print("  none")
        print(
            "\nRaw source rows remain preserved. Snapshot values are "
            "research-only unless a separate, explicit cross-source "
            "attestation promotes an individual field."
        )
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(db.DB_PATH), help="SQLite database (opened read-only)")
    parser.add_argument("--as-of", help="Export snapshot date YYYY-MM-DD")
    args = parser.parse_args(argv)
    report(args.db, args.as_of)


if __name__ == "__main__":
    main()
