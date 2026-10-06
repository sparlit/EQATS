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


import datetime as dt
import sys

import db
import pandas as pd
from fundamentals_store import merge

NUMERIC = [
    "current_price",
    "market_cap_cr",
    "pe",
    "pb",
    "roe",
    "roce",
    "debt_to_equity",
    "interest_coverage",
    "operating_margin",
    "net_profit_margin",
    "sales_growth_3y",
    "profit_growth_3y",
    "promoter_holding",
    "pledge_pct",
    "fii_holding",
    "dividend_yield",
    "roic",
    "beta_1y",
    "eps_fy",
    "book_value",
    "ev_ebitda",
    "fcf_fy",
    "net_debt_fy",
    "cfo_positive",
]


def load(path):
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "symbol" not in df.columns:
        print("CSV must have a 'symbol' column")
        return
    for c in NUMERIC:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    conn = db.get_conn()
    import hashlib
    import os

    with open(path, "rb") as source:
        source_hash = hashlib.sha256(source.read()).hexdigest()
    metadata = {
        "filename": os.path.basename(path),
        "sha256": source_hash,
        "source_modified_at": dt.datetime.fromtimestamp(os.path.getmtime(path))
        .astimezone()
        .isoformat(),
        "imported_at": dt.datetime.now().astimezone().isoformat(),
        "source_observation_date": None,
        "financial_period_end": None,
    }
    n = 0
    for _, r in df.iterrows():
        sym = str(r["symbol"]).strip().upper()
        for suffix in (".NS", ".NSE", ".BO", ".BSE"):
            if sym.endswith(suffix):
                sym = sym[: -len(suffix)]
                break
        if not sym:
            continue
        vals = {"symbol": sym}
        for col in NUMERIC + ["name", "sector", "cfo_positive"]:
            value = r.get(col)
            if pd.notna(value):
                vals[col] = int(value) if col == "cfo_positive" else value
        vals["data_quality_flags"] = [
            "source_observation_date_unknown",
            "financial_period_end_unknown",
            "publication_time_unknown",
        ]
        vals["source_metadata"] = metadata
        merge(conn, vals, source="fundamentals_csv", observed_at=metadata["imported_at"])
        n += 1
    conn.commit()
    print(f"Fundamentals CSV loaded: {n} stocks (non-null fields merged)")
    conn.close()


if len(sys.argv) > 1:
    load(sys.argv[1])
