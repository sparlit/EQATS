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


"""
A1 — Fundamentals refresh (weekly / on-call).
Modes:
  csv   -> ingest data/fundamentals.csv (screener export), flexible headers
  yahoo -> best-effort yfinance refresh for top-N symbols
  auto  -> csv if present, then yahoo
"""
import datetime as dt
import hashlib
import os
import sys
import time

import db
import pandas as pd
from fundamentals_store import merge

CSV_PATH = "data/fundamentals.csv"

ALIASES = {
    "symbol": "symbol",
    "company": "symbol",
    "ticker": "symbol",
    "roce": "roce",
    "return_on_capital_employed": "roce",
    "roe": "roe",
    "return_on_equity": "roe",
    "roic": "roic",
    "return_on_invested_capital": "roic",
    "pe": "pe",
    "p/e": "pe",
    "pe_ratio": "pe",
    "trailing_pe": "pe",
    "debt_to_equity": "debt_to_equity",
    "debt_eq": "debt_to_equity",
    "d/e": "debt_to_equity",
    "de_ratio": "debt_to_equity",
    "promoter_holding": "promoter_holding",
    "promoter": "promoter_holding",
    "promoter_pct": "promoter_holding",
    "mcap_cr": "market_cap_cr",
    "market_cap_cr": "market_cap_cr",
}


def _norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum() or ch == "_")


def _clean_symbol(x):
    s = str(x).strip().upper()
    for suf in (".NS", ".NSE", ".BO", ".BSE"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s


def _table_cols(conn):
    return [r[1] for r in conn.execute("PRAGMA table_info(fundamentals)")]


def _sha256_file(path):
    with open(path, "rb") as source:
        return hashlib.sha256(source.read()).hexdigest()


def _upsert(conn, vals, source, source_metadata=None):
    vals = dict(vals)
    vals["data_quality_flags"] = ["financial_period_end_unknown", "publication_time_unknown"]
    if source_metadata is not None:
        vals["source_metadata"] = source_metadata
    return merge(conn, vals, source=source)


def ingest_csv(path=CSV_PATH):
    if not os.path.exists(path):
        print(f"[FUND] no csv at {path}")
        return 0
    conn = db.get_conn()
    import_metadata = {
        "filename": os.path.basename(path),
        "sha256": _sha256_file(path),
        "source_modified_at": dt.datetime.fromtimestamp(os.path.getmtime(path))
        .astimezone()
        .isoformat(),
        "imported_at": dt.datetime.now().astimezone().isoformat(),
        "source_observation_date": None,
        "financial_period_end": None,
    }
    table_cols = set(_table_cols(conn))
    df = pd.read_csv(path)
    colmap = {}
    for c in df.columns:
        key = _norm(ALIASES.get(_norm(c), c))
        if key in table_cols:
            colmap[c] = key
    if "symbol" not in colmap.values():
        print("[FUND] csv has no symbol column")
        conn.close()
        return 0
    n = 0
    for _, row in df.iterrows():
        vals = {}
        for c, key in colmap.items():
            v = row[c]
            if pd.isna(v):
                continue
            if key == "symbol":
                vals[key] = _clean_symbol(v)
            elif key in {"name", "sector"}:
                vals[key] = str(v).strip()
            else:
                try:
                    vals[key] = float(str(v).replace(",", "").replace("%", ""))
                except Exception:
                    continue
        if vals.get("symbol"):
            _upsert(conn, vals, "fundamentals_csv", import_metadata)
            n += 1
    conn.commit()
    conn.close()
    print(f"[FUND] ingested {n} rows from csv")
    return n


def refresh_yahoo(limit=100):
    import yfinance as yf

    conn = db.get_conn()
    table_cols = set(_table_cols(conn))
    syms = [
        r[0]
        for r in conn.execute(
            "SELECT symbol FROM universe_broad ORDER BY mcap_cr DESC LIMIT ?", (limit,)
        )
    ]
    n = 0
    for sym in syms:
        try:
            info = yf.Ticker(sym + ".NS").info or {}
        except Exception:
            continue
        vals = {"symbol": sym}

        def put(col, key, scale=1.0):
            v = info.get(key)
            if col in table_cols and isinstance(v, (int, float)):
                vals[col] = float(v) * scale

        put("pe", "trailingPE")
        put("debt_to_equity", "debtToEquity", 0.01)
        put("promoter_holding", "heldPercentInsiders", 100.0)
        put("roe", "returnOnEquity", 100.0)
        put("market_cap_cr", "marketCap", 1e-7)

        if len(vals) > 1:
            _upsert(
                conn,
                vals,
                "yahoo_finance",
                {
                    "retrieved_at": dt.datetime.now().astimezone().isoformat(),
                    "source_observation_date": None,
                    "financial_period_end": None,
                },
            )
            n += 1
        time.sleep(0.3)
    conn.commit()
    conn.close()
    print(f"[FUND] yahoo refreshed {n} symbols")
    return n


def auto():
    ingest_csv()
    try:
        refresh_yahoo(100)
    except Exception as e:
        print(f"[FUND] yahoo refresh skipped: {e}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode == "csv":
        ingest_csv()
    elif mode == "yahoo":
        refresh_yahoo()
    else:
        auto()
