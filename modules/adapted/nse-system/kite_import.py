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


"""Import a KITE watchlist export into an isolated research snapshot table.

The export has no financial-period or publication dates and must not update
live fundamentals, daily prices, trading signals, or historical replays.
"""

import argparse
import csv
import datetime as dt
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path

from data_sources.provenance import file_metadata
from scanx_import import ALIASES, _master_index, _norm

from config import DB_PATH

# Abbreviated KITE display names manually matched to unique EQ-series entries
# in the contemporaneous NSE security master. Fuzzy matches are never applied.
KITE_ALIASES = {
    "AADHAR HOUSING FINANCE L": "AADHARHFC",
    "ADANI ENERGY SOLUTION": "ADANIENSOL",
    "ADITYA BIRLA FASHION & RT": "ABFRL",
    "ADITYA BIRLA REAL EST": "ABREL",
    "AMBER ENTERPRISES (I)": "AMBER",
    "BOMBAY BURMAH TRADING COR": "BBTC",
    "CCL PRODUCTS (I)": "CCL",
    "EMCURE PHARMACEUTICALS L": "EMCURE",
    "EMMVEE PHOTOVOLTAIC PWR L": "EMMVEE",
    "HEG ADVANCED MATERIAL": "HEGAM",
    "HIMADRI SPECIALITY CHEM L": "HSCL",
    "HONEYWELL AUTOMATION IND": "HONAUT",
    "INFO EDGE (I)": "NAUKRI",
    "JAIN RESOURCE RECYCLING L": "JAINREC",
    "KALYAN JEWELLERS IND": "KALYANKJIL",
    "KAYNES TECHNOLOGY IND": "KAYNES",
    "LLOYDS METALS N ENERGY L": "LLOYDSME",
    "MAZAGON DOCK SHIPBUIL": "MAZDOCK",
    "MULTI COMMODITY EXCHANGE": "MCX",
    "NUVAMA WEALTH MANAGE": "NUVAMA",
    "SHYAM METALICS AND ENGY L": "SHYAMMETL",
    "TATA CONSUMER PRODUCT": "TATACONSUM",
    "TORRENT PHARMACEUTICALS L": "TORNTPHARM",
    "VEDANTA ALUMINIUM METAL L": "VAML",
    "VIJAYA DIAGNOSTIC CEN": "VIJAYA",
}

NORMALIZED_ALIASES = {}
for label, symbol in {**ALIASES, **KITE_ALIASES}.items():
    key = _norm(label)
    previous = NORMALIZED_ALIASES.get(key)
    if previous is not None and previous != symbol:
        msg = f"Conflicting curated KITE alias: {label!r}"
        raise ValueError(msg)
    NORMALIZED_ALIASES[key] = symbol

VALUE_COLUMNS = {
    "average_price": ("Average Price",),
    "buy_quantity": ("Buy Quantity",),
    "change_value": ("Change",),
    "change_pct": ("Change %",),
    "previous_close": ("Previous Close",),
    "debt_to_equity": ("Debt to Equity",),
    "dividend_yield": ("Dividend Yield",),
    "free_cash_flow": ("Free Cash Flow",),
    "day_high": ("Day High",),
    "last_price": ("Last Price",),
    "day_low": ("Day Low",),
    "lower_circuit_limit": ("Lower Circuit Limit",),
    "market_cap_cr": ("Market Cap (Cr)", "Market Cap (Cr.)"),
    "open_price": ("Open",),
    "profit_growth_yoy": ("Profit Growth YoY (%)",),
    "pe": ("P/E Ratio",),
    "revenue_growth_yoy": ("Revenue Growth YoY (%)",),
    "roe": ("Return on Equity",),
    "sell_quantity": ("Sell Quantity",),
    "trade_value_cr": ("Trade Value (Cr)",),
    "upper_circuit_limit": ("Upper Circuit Limit",),
    "volume": ("Volume",),
    "week_52_high": ("52 Week High",),
    "week_52_low": ("52 Week Low",),
}

ZERO_SENTINEL_SOURCE_FIELDS = {
    "Average Price": "average_price",
    "Buy Quantity": "buy_quantity",
    "Sell Quantity": "sell_quantity",
    "Trade Value (Cr)": "trade_value_cr",
    "Volume": "volume",
}


def _read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            msg = f"{path} has no CSV header"
            raise ValueError(msg)
        rows = []
        for row in reader:
            rows.append({str(key).strip(): (value or "").strip() for key, value in row.items()})
        return rows


def _number(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"-", "--", "na", "n/a", "null", "none"}:
        return None
    text = text.replace(",", "").replace("%", "").strip()
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _zero_sentinels(rows):
    sentinels = set()
    for source_field in ZERO_SENTINEL_SOURCE_FIELDS:
        values = [_number(row.get(source_field)) for row in rows]
        if values and all(value == 0 for value in values):
            sentinels.add(source_field)
    return sentinels


def _instrument_map(instrument, by_name, by_symbol):
    key = _norm(instrument)
    named = by_name.get(key, {})
    if len(named) == 1:
        return next(iter(named.values())), "normalized_exact"
    if len(named) > 1:
        return None, "ambiguous_company_name"

    alias_symbol = NORMALIZED_ALIASES.get(key)
    if alias_symbol:
        security = by_symbol.get(alias_symbol)
        if security is None:
            msg = f"Curated alias {instrument!r} points to missing NSE security-master symbol {alias_symbol!r}"
            raise ValueError(msg)
        return security, "curated_alias"

    symbol_matches = [record for symbol, record in by_symbol.items() if _norm(symbol) == key]
    if len(symbol_matches) == 1:
        return symbol_matches[0], "exact_symbol"
    if len(symbol_matches) > 1:
        return None, "ambiguous_symbol"
    return None, "unmatched"


def _snapshot_rows(rows, master_path, as_of, source_path):
    if not rows:
        msg = "KITE export has no data rows"
        raise ValueError(msg)
    if any(not row.get("Instrument", "").strip() for row in rows):
        msg = "KITE export contains a row without Instrument"
        raise ValueError(msg)

    grouped = {}
    for row in rows:
        key = _norm(row["Instrument"])
        if key in grouped:
            if grouped[key]["row"] != row:
                msg = f"Conflicting duplicate KITE instrument: {row['Instrument']!r}"
                raise ValueError(msg)
            grouped[key]["duplicate_row_count"] += 1
        else:
            grouped[key] = {"row": row, "duplicate_row_count": 1}

    by_name, by_symbol = _master_index(master_path)
    sentinels = _zero_sentinels(rows)
    source_metadata = file_metadata(source_path)
    master_metadata = file_metadata(master_path)
    snapshots = []
    mapped_symbols = set()
    for instrument_key, item in sorted(grouped.items()):
        row = item["row"]
        instrument = row["Instrument"].strip()
        security, match_method = _instrument_map(instrument, by_name, by_symbol)
        symbol = security["symbol"] if security else None
        if symbol and symbol in mapped_symbols:
            msg = f"Multiple KITE instruments map to {symbol}; refusing an ambiguous import"
            raise ValueError(msg)
        if symbol:
            mapped_symbols.add(symbol)

        values = {}
        flags = []
        for column, source_names in VALUE_COLUMNS.items():
            source_name = next((name for name in source_names if name in row), None)
            value = _number(row.get(source_name)) if source_name else None
            if source_name in sentinels:
                flags.append(f"unavailable_sentinel:{column}")
                value = None
            values[column] = value

        range_limits = {
            "change_pct": (-100, 100),
            "debt_to_equity": (0, 100),
            "dividend_yield": (0, 100),
            "pe": (0, 1000),
            "profit_growth_yoy": (-100, 1000),
            "revenue_growth_yoy": (-100, 1000),
            "roe": (-100, 200),
        }
        for column, (minimum, maximum) in range_limits.items():
            value = values[column]
            if value is not None and (value < minimum or value > maximum):
                flags.append(f"out_of_range:{column}")
                values[column] = None

        for column in ("day_high", "day_low", "last_price", "open_price", "previous_close"):
            value = values[column]
            if value is not None and value <= 0:
                flags.append(f"out_of_range:{column}")
                values[column] = None

        if not symbol:
            flags.append(f"symbol_{match_method}")
        if item["duplicate_row_count"] > 1:
            flags.append("duplicate_identical_source_rows")

        snapshots.append(
            {
                "as_of_date": as_of,
                "instrument_key": instrument_key,
                "instrument": instrument,
                "symbol": symbol,
                "isin": security["isin"] if security else None,
                "company_name": security["company_name"] if security else None,
                "sector": row.get("Sector") or None,
                "financial_period_end": None,
                "published_at": None,
                **values,
                "mapping_method": match_method,
                "duplicate_row_count": item["duplicate_row_count"],
                "data_quality_flags": json.dumps(sorted(flags), separators=(",", ":")),
                "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
                "source_file": Path(source_path).name,
                "source_sha256": source_metadata["sha256"],
                "source_modified_at": source_metadata["modified_at"],
                "security_master_file": master_metadata["file_name"],
                "security_master_sha256": master_metadata["sha256"],
            }
        )
    return snapshots, sentinels, len(rows)


def _backup(database):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = database.with_name(f"{database.name}.pre-kite-{stamp}.bak")
    source_conn = sqlite3.connect(str(database))
    backup_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()
    return target


def _apply(database, snapshots):
    columns = {
        "as_of_date": "TEXT NOT NULL",
        "instrument_key": "TEXT NOT NULL",
        "instrument": "TEXT NOT NULL",
        "symbol": "TEXT",
        "isin": "TEXT",
        "company_name": "TEXT",
        "sector": "TEXT",
        "financial_period_end": "TEXT",
        "published_at": "TEXT",
        **dict.fromkeys(VALUE_COLUMNS, "REAL"),
        "mapping_method": "TEXT NOT NULL",
        "duplicate_row_count": "INTEGER NOT NULL DEFAULT 1",
        "data_quality_flags": "TEXT NOT NULL DEFAULT '[]'",
        "raw_json": "TEXT NOT NULL",
        "source_file": "TEXT NOT NULL",
        "source_sha256": "TEXT",
        "source_modified_at": "TEXT",
        "security_master_file": "TEXT",
        "security_master_sha256": "TEXT",
        "imported_at": "TEXT NOT NULL",
    }
    conn = sqlite3.connect(str(database), timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        definitions = ", ".join(f"{name} {kind}" for name, kind in columns.items())
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kite_market_snapshots ("
            f"{definitions}, "
            "PRIMARY KEY (as_of_date, instrument_key))"
        )
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(kite_market_snapshots)")}
        for name, kind in columns.items():
            if name not in existing_columns:
                conn.execute(f"ALTER TABLE kite_market_snapshots ADD COLUMN {name} {kind}")
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        imported_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        column_names = list(columns)
        insert_sql = (
            "INSERT INTO kite_market_snapshots "
            f"({','.join(column_names)}) "
            f"VALUES ({','.join('?' for _ in column_names)}) "
            "ON CONFLICT(as_of_date,instrument_key) DO UPDATE SET "
            + ",".join(
                f"{name}=excluded.{name}" for name in column_names if name not in ("as_of_date", "instrument_key")
            )
        )
        for snapshot in snapshots:
            values = dict(snapshot, imported_at=imported_at)
            conn.execute(insert_sql, [values.get(name) for name in column_names])
        conn.commit()
        return len(snapshots)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _print_summary(snapshots, duplicate_source_rows, sentinels, source_path, apply_result=None):
    matched = sum(row["symbol"] is not None for row in snapshots)
    counts = Counter(row["mapping_method"] for row in snapshots)
    print(f"KITE export: {Path(source_path).name}")
    print(f"Snapshot date: {snapshots[0]['as_of_date']} (derived from file modification date; not a financial period)")
    print(f"Unique instruments: {len(snapshots)}; mapped: {matched}; unmapped/ambiguous: {len(snapshots) - matched}")
    print(f"Duplicate identical source rows omitted: {duplicate_source_rows}")
    print("Mappings: " + ", ".join(f"{name}={count}" for name, count in sorted(counts.items())))
    print("All-zero unavailable fields: " + (", ".join(sorted(sentinels)) if sentinels else "none"))
    if snapshots:
        print(f"Source SHA-256: {snapshots[0]['source_sha256']}")
        print(f"NSE security-master SHA-256: {snapshots[0]['security_master_sha256']}")
    if apply_result is not None:
        print(f"Inserted/updated {apply_result} research snapshots.")
    unmatched = [row["instrument"] for row in snapshots if not row["symbol"]]
    if unmatched:
        print("Unmapped instrument labels (retained without a symbol):")
        print(", ".join(unmatched))
    print(
        "Financial period and public filing time are unknown. "
        "Snapshots do not feed live fundamentals, prices, signals, "
        "or backtests."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", nargs="?", default="data/incoming/KITE.csv", help="KITE CSV export")
    parser.add_argument(
        "--master", default="data/incoming/nse_equity_master.csv", help="NSE EQUITY_L.csv security master"
    )
    parser.add_argument("--as-of", help="Snapshot date YYYY-MM-DD; defaults to file date")
    parser.add_argument("--db", default=str(DB_PATH), help="Target SQLite database")
    parser.add_argument("--apply", action="store_true", help="Back up the database, then import")
    args = parser.parse_args(argv)
    source = Path(args.csv)
    master = Path(args.master)
    database = Path(args.db)
    if not source.is_file() or not master.is_file():
        msg = "KITE CSV or NSE security master not found"
        raise FileNotFoundError(msg)
    if args.apply and not database.is_file():
        msg = f"Target database does not exist: {database}"
        raise FileNotFoundError(msg)

    rows = _read_csv(source)
    modified_at = dt.datetime.fromtimestamp(source.stat().st_mtime).astimezone()
    as_of = dt.date.fromisoformat(args.as_of).isoformat() if args.as_of else modified_at.date().isoformat()
    snapshots, sentinels, source_rows = _snapshot_rows(rows, master, as_of, source)
    duplicates = source_rows - len(snapshots)
    _print_summary(snapshots, duplicates, sentinels, source)
    if args.apply:
        backup = _backup(database.resolve())
        written = _apply(database.resolve(), snapshots)
        print(f"Backup: {backup}")
        _print_summary(snapshots, duplicates, sentinels, source, written)


if __name__ == "__main__":
    main()
