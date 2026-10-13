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


"""Import a dated ScanX fundamentals export using an NSE security master.

The import is a current snapshot, not point-in-time historical data.
Unmatched names are deliberately left out instead of fuzzy-matched.
"""
import argparse
import csv
import datetime as dt
import json
import math
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

import db
from data_sources.provenance import file_metadata

ALIASES = {
    "LIC of India": "LICI",
    "Sun Pharmaceutical": "SUNPHARMA",
    "Adani Ports & SEZ": "ADANIPORTS",
    "Kotak Bank": "KOTAKBANK",
    "Avenue Supermarts DMart": "DMART",
    "TVS Motors": "TVSMOTOR",
    "Cholamandalam Investment": "CHOLAFIN",
    "Apollo Hospitals": "APOLLOHOSP",
    "Bajaj Holdings & Investments": "BAJAJHLDNG",
    "Zydus Life Science": "ZYDUSLIFE",
    "Groww": "GROWW",
    "IRFC": "IRFC",
    "HDFC AMC": "HDFCAMC",
    "Nykaa": "NYKAA",
    "MCX": "MCX",
    "Nippon Life India AMC": "NAM-INDIA",
    "NALCO": "NATIONALUM",
    "GIC of India": "GICRE",
    "SBI Cards": "SBICARD",
    "Berger Paints": "BERGEPAINT",
    "Fertilisers & Chemical Travancore": "FACT",
    "Tube Investment": "TIINDIA",
    "Authum Inv & Infr": "AIIL",
    "M&M Financial Services": "M&MFIN",
    "IRCTC": "IRCTC",
    "HUDCO": "HUDCO",
    "Syrma SGS": "SYRMA",
    "Star Health Insurance": "STARHEALTH",
    "IREDA": "IREDA",
    "Schneider Electric Infra": "SCHNEIDER",
    "Mangalore Refinery & Petroleum": "MRPL",
    "CDSL": "CDSL",
    "ZF Commercial": "ZFCVINDIA",
    "Garden Reach Shipbuilders": "GRSE",
    "EIH Hotels": "EIHOTEL",
    "Triveni Turbines": "TRITURBINE",
    "CAMS": "CAMS",
    "Deepak Fertilisers & Petrochemicals": "DEEPAKFERT",
    "Chambal Fertilisers & Chemicals": "CHAMBLFERT",
    "DCM Shriram Consolidated": "DCMSHRIRAM",
    "Mamaearth": "HONASA",
    "Crompton Greaves": "CROMPTON",
    "Akums Drugs & Pharma": "AKUMS",
    "Whirlpool": "WHIRLPOOL",
    "UTI AMC": "UTIAMC",
    "Yatharth Hospital": "YATHARTH",
    "Paras Defence Space Tech": "PARAS",
    "RateGain Travel": "RATEGAIN",
    "Firstcry (Brainbees Solutions)": "FIRSTCRY",
    "Gujarat Narmada Valley Fert & Chem": "GNFC",
    "Jupiter Life Line Hospital": "JLHL",
    "Banco Products": "BANCOINDIA",
    "Axiscades Engineering Technologies": "AXISCADES",
    "Zee Entertainment": "ZEEL",
    "Jyothy Laboratories": "JYOTHYLAB",
    "Le Travenues Technology (IXIGO)": "IXIGO",
    "Mrs. Bectors Food": "BECTORFOOD",
    "Restaurant Brand Asia (Burger King)": "RBA",
    "Advanced Enzyme Tech": "ADVENZYMES",
}

# Out-of-range values are quarantined from structured use, never clipped;
# the exact source strings remain in raw_json for review.
STRUCTURED_FIELDS = {
    "roe_avg_3y": ("Average ROE 3Years", -100, 100),
    "roe_avg_10y": ("Average ROE 10Years", -100, 100),
    "roa_avg_3y": ("Return on assets 3years", -100, 100),
    "roa_avg_5y": ("Return on assets 5years", -100, 100),
    "opm_avg_5y": ("OPM 5Year", -100, 100),
    "opm_avg_10y": ("OPM 10 Year", -100, 100),
    "roce_growth_5y": ("ROCE Growth % (5 Year)", -100, 500),
    "roe_growth_5y": ("ROE Growth % (5 Year)", -100, 300),
    "quarter_sales_yoy_growth": ("YoY last Quarterly Sales Growth", -100, 1000),
    "quarter_profit_yoy_growth": ("YoY last Quarterly Profit Growth", -100, 1000),
    "annual_revenue_growth": ("Revenue Growth (Year)", -100, 1000),
    "sales_growth_qoq": ("Sales growth (QoQ)", -100, 1000),
    "profit_growth_qoq": ("Profit growth QoQ", -100, 1000),
    "free_cash_flow": ("Free Cash Flow", None, None),
    "net_income_quarterly": ("Net Income (Quarterly)", None, None),
    "profit_after_tax": ("Profit After Tax (PAT)", None, None),
    "net_change_in_cash": ("Net Change in Cash", None, None),
    "change_in_working_capital": ("Change In Working Capital", None, None),
    "annual_sales": ("Sales", None, None),
    "current_assets": ("Current Assets", None, None),
    "current_liabilities": ("Current Liabilities", None, None),
    "total_assets": ("Total Assets", None, None),
    "total_liabilities": ("Total Liabilities", None, None),
    "total_equity": ("Total Equity", None, None),
    "inventory": ("Total Inventory", None, None),
    "capex_growth": ("Increase in CAPEX %", -100, 2000),
    "fixed_assets": ("Fixed Assets", None, None),
    "investments": ("Investments", None, None),
    "investing_cash_flow": ("Investing Cash Flow", None, None),
    "financing_cash_flow": ("Finanacing Cash Flow", None, None),
    "dividend_per_share": ("Dividend Per Share", 0, None),
    "payout_ratio": ("Payout Ratio", 0, 500),
    "ev_ebitda": ("EV/EBITDA", 0, 200),
    "pe_sector_ratio": ("PE/Sector PE", 0, 20),
    "market_cap_sales": ("Market Cap/Sales", 0, 200),
    "industry_eps": ("Industry EPS", None, None),
    "industry_pe": ("Industry PE Ratio", 0, 500),
    "industry_pb": ("Industry PB Ratio", 0, 100),
    "industry_dividend_yield": ("Industry Dividend Yield", 0, 100),
    "industry_operating_margin": ("Industry Operating Margin", -100, 100),
    "dii_holding_change": ("Change in DII holding", -100, 100),
    "fii_holding_change": ("Change in FII holding", -100, 100),
    "public_holding": ("Public / Retail Holding %", 0, 100),
    "promoter_holding_change": ("Change in promoter holding", -100, 100),
}

# These export columns were identically zero across all 750 source rows.
ZERO_SENTINEL_FIELDS = {
    "Payout Ratio": "payout_ratio",
    "Change in promoter holding": "promoter_holding_change",
}

SNAPSHOT_BASE_COLUMNS = {
    "as_of_date": "TEXT NOT NULL",
    "symbol": "TEXT NOT NULL",
    "isin": "TEXT",
    "scanx_name": "TEXT",
    "company_name": "TEXT",
    "sector": "TEXT",
    "financial_period_end": "TEXT",
    "published_at": "TEXT",
    "current_price": "REAL",
    "market_cap_cr": "REAL",
    "pe": "REAL",
    "pb": "REAL",
    "roe": "REAL",
    "roce": "REAL",
    "debt_to_equity": "REAL",
    "operating_margin": "REAL",
    "net_profit_margin": "REAL",
    "promoter_holding": "REAL",
    "fii_holding": "REAL",
    "dii_holding": "REAL",
    "dividend_yield": "REAL",
    "operating_cash_flow": "REAL",
    "cfo_positive": "INTEGER",
    **dict.fromkeys(STRUCTURED_FIELDS, "REAL"),
    "data_quality_flags": "TEXT NOT NULL DEFAULT '[]'",
    "raw_json": "TEXT NOT NULL",
    "match_method": "TEXT NOT NULL",
    "source_file": "TEXT NOT NULL",
    "source_sha256": "TEXT",
    "source_modified_at": "TEXT",
    "security_master_file": "TEXT",
    "security_master_sha256": "TEXT",
    "imported_at": "TEXT NOT NULL",
}


def _norm(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    tokens = re.findall(r"[a-z0-9]+", text.replace("&", " and "))
    while tokens and tokens[0] == "the":
        tokens.pop(0)
    while tokens and tokens[-1] in {
        "limited",
        "ltd",
        "incorporated",
        "inc",
        "corporation",
        "corp",
        "company",
        "co",
        "india",
    }:
        tokens.pop()
    return "".join(tokens)


def _read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no CSV header")
        return [{str(k).strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _master_index(path):
    rows = _read_csv(path)
    by_name = defaultdict(dict)
    by_symbol = {}
    for row in rows:
        symbol = row.get("SYMBOL", "").upper()
        series = row.get("SERIES", "").upper()
        if not symbol or series not in {"EQ", "BE", "BZ"}:
            continue
        record = {
            "symbol": symbol,
            "isin": row.get("ISIN NUMBER", ""),
            "company_name": row.get("NAME OF COMPANY", ""),
        }
        by_name[_norm(record["company_name"])][symbol] = record
        by_symbol[symbol] = record
    return by_name, by_symbol


def _resolve(rows, by_name, by_symbol):
    mapped, unmatched = [], []
    for row in rows:
        name = row.get("Name", "")
        override = ALIASES.get(name)
        if override:
            security = by_symbol.get(override)
            method = "curated_alias"
            if security is None:
                raise ValueError(f"Alias {name!r} points to missing NSE EQ symbol {override!r}")
        else:
            candidates = by_name.get(_norm(name), {})
            if len(candidates) != 1:
                unmatched.append(name)
                continue
            security = next(iter(candidates.values()))
            method = "normalized_exact"
        mapped.append(
            {
                "scanx_name": name,
                "symbol": security["symbol"],
                "isin": security["isin"],
                "company_name": security["company_name"],
                "match_method": method,
                "row": row,
            }
        )

    seen = set()
    for item in mapped:
        if item["symbol"] in seen:
            raise ValueError(
                f"Multiple ScanX rows map to {item['symbol']}; refusing an ambiguous import"
            )
        seen.add(item["symbol"])
    return mapped, unmatched


def _number(row, *names):
    for name in names:
        value = row.get(name, "")
        if not value or value.strip().lower() in {"-", "--", "na", "n/a", "null", "none"}:
            continue
        value = value.replace(",", "").replace("%", "").strip()
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            continue
    return None


def _zero_sentinel_fields(rows):
    sentinels = set()
    for source_name in ZERO_SENTINEL_FIELDS:
        values = [_number(row, source_name) for row in rows]
        if values and all(value == 0 for value in values):
            sentinels.add(source_name)
    return sentinels


def _snapshot_values(item, as_of, sentinel_fields=None):
    row = item["row"]
    sentinel_fields = sentinel_fields or set()
    cfo = _number(row, "Operating Cash Flow")
    snapshot = {
        "as_of_date": as_of,
        "symbol": item["symbol"],
        "isin": item["isin"],
        "scanx_name": item["scanx_name"],
        "company_name": item["company_name"],
        "sector": row.get("Industry") or None,
        "financial_period_end": None,
        "published_at": None,
        "current_price": _number(row, "Close Price", "Price"),
        "market_cap_cr": _number(row, "Market Cap (Cr.)"),
        "pe": _number(row, "P/E Ratio"),
        "pb": _number(row, "PB Ratio"),
        "roe": _number(row, "Return on Equity", "Average ROE 3Years"),
        "roce": _number(row, "Return on Capital Employed"),
        "debt_to_equity": _number(row, "Debt to Equity"),
        "operating_margin": _number(row, "OPM"),
        "net_profit_margin": _number(row, "Net Profit Margin"),
        "promoter_holding": _number(row, "Promoter Holding %"),
        "fii_holding": _number(row, "FII Holding"),
        "dii_holding": _number(row, "DII Holding"),
        "dividend_yield": _number(row, "Dividend Yield"),
        "operating_cash_flow": cfo,
        "cfo_positive": None if cfo is None else int(cfo > 0),
        "raw_json": json.dumps(row, ensure_ascii=False, sort_keys=True),
        "match_method": item["match_method"],
    }
    quality_flags = []
    for source_name, column in ZERO_SENTINEL_FIELDS.items():
        if source_name in sentinel_fields:
            quality_flags.append(f"unavailable_sentinel:{column}")
    for column, (source_name, minimum, maximum) in STRUCTURED_FIELDS.items():
        value = None if source_name in sentinel_fields else _number(row, source_name)
        if value is not None and (
            (minimum is not None and value < minimum) or (maximum is not None and value > maximum)
        ):
            quality_flags.append(f"out_of_range:{column}")
            value = None
        snapshot[column] = value
    snapshot["data_quality_flags"] = json.dumps(sorted(quality_flags), separators=(",", ":"))
    return snapshot


def _backup(path):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.pre-scanx-{stamp}.bak")
    source_conn = sqlite3.connect(str(path))
    backup_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()
    return target


def _apply(path, snapshots, source_file, security_master_file):
    conn = sqlite3.connect(str(path))
    try:
        imported_at = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        source_metadata = file_metadata(source_file)
        master_metadata = file_metadata(security_master_file)
        definitions = ", ".join(
            f"{column} {kind}" for column, kind in SNAPSHOT_BASE_COLUMNS.items()
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS scanx_fundamentals_snapshots ("
            f"{definitions}, PRIMARY KEY (as_of_date, symbol))"
        )
        table_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(scanx_fundamentals_snapshots)")
        }
        for column, kind in SNAPSHOT_BASE_COLUMNS.items():
            if column in table_columns:
                continue
            conn.execute(f"ALTER TABLE scanx_fundamentals_snapshots ADD COLUMN {column} {kind}")
        conn.commit()
        conn.execute("BEGIN")
        snapshot_cols = list(SNAPSHOT_BASE_COLUMNS)
        for snapshot in snapshots:
            values = dict(snapshot)
            values.update(
                source_file=Path(source_file).name,
                source_sha256=source_metadata["sha256"],
                source_modified_at=source_metadata["modified_at"],
                security_master_file=master_metadata["file_name"],
                security_master_sha256=master_metadata["sha256"],
                imported_at=imported_at,
            )
            conn.execute(
                "INSERT INTO scanx_fundamentals_snapshots "
                f"({','.join(snapshot_cols)}) VALUES "
                f"({','.join('?' for _ in snapshot_cols)}) "
                "ON CONFLICT(as_of_date,symbol) DO UPDATE SET "
                + ",".join(
                    f"{key}=excluded.{key}"
                    for key in snapshot_cols
                    if key not in ("as_of_date", "symbol")
                ),
                [values.get(key) for key in snapshot_cols],
            )
        conn.commit()
        return imported_at, len(snapshots)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="ScanX export CSV")
    parser.add_argument(
        "--master",
        default="data/incoming/nse_equity_master.csv",
        help="NSE EQUITY_L.csv security master",
    )
    parser.add_argument("--as-of", required=True, help="Snapshot date YYYY-MM-DD")
    parser.add_argument("--db", default=str(db.DB_PATH), help="Target SQLite database")
    parser.add_argument("--apply", action="store_true", help="Back up the database, then import")
    args = parser.parse_args(argv)
    as_of = dt.date.fromisoformat(args.as_of).isoformat()
    source = Path(args.csv)
    master = Path(args.master)
    if not source.is_file() or not master.is_file():
        raise FileNotFoundError("ScanX CSV or NSE security master not found")
    rows = _read_csv(source)
    by_name, by_symbol = _master_index(master)
    mapped, unmatched = _resolve(rows, by_name, by_symbol)
    if not mapped:
        raise RuntimeError("No ScanX company names could be mapped")
    sentinels = _zero_sentinel_fields(rows)
    snapshots = [_snapshot_values(item, as_of, sentinels) for item in mapped]
    if args.apply:
        target = Path(args.db).resolve()
        if not target.is_file():
            raise FileNotFoundError(f"Target database does not exist: {target}")
        backup = _backup(target)
        imported_at, written = _apply(target, snapshots, source, master)
        print(
            f"Imported {len(snapshots)} dated ScanX snapshots "
            f"({as_of}; {imported_at}) into {target}"
        )
        print(
            f"Inserted/updated {written} rows only in "
            "scanx_fundamentals_snapshots; live fundamentals and trading "
            "universe tables were not changed."
        )
        print(f"Pre-import database backup: {backup}")
    else:
        print(
            f"Dry run: {len(snapshots)} unique mapped rows; "
            f"{len(unmatched)} unmatched; snapshot date {as_of}; "
            f"{len(STRUCTURED_FIELDS)} structured research fields"
        )
    if sentinels:
        print(
            "All-zero source columns withheld from structured metrics "
            "(original values remain in raw_json):"
        )
        for name in sorted(sentinels):
            print(f"  {name}")
    if unmatched:
        print("Unmatched company names (not imported):")
        for name in unmatched:
            print(f"  {name}")
    print(
        "The export date is not a financial period-end or filing date. "
        "ScanX metrics do not feed live scoring, vetoes, or backtests."
    )


if __name__ == "__main__":
    main()
