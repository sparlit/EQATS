"""
A1 — Fundamentals refresh (weekly / on-call).
Modes:
  csv   -> ingest data/fundamentals.csv (screener export), flexible headers
  yahoo -> best-effort yfinance refresh for top-N symbols
  auto  -> csv if present, then yahoo
"""
import os
import sys
import time
import pandas as pd
import db

CSV_PATH = "data/fundamentals.csv"

ALIASES = {
    "symbol": "symbol", "company": "symbol", "ticker": "symbol",
    "roce": "roce", "return_on_capital_employed": "roce",
    "return_on_equity": "roce",
    "pe": "pe", "p/e": "pe", "pe_ratio": "pe", "trailing_pe": "pe",
    "debt_to_equity": "debt_to_equity", "d/e": "debt_to_equity",
    "de_ratio": "debt_to_equity",
    "promoter_holding": "promoter_holding", "promoter": "promoter_holding",
    "promoter_pct": "promoter_holding",
    "mcap_cr": "mcap_cr", "market_cap_cr": "mcap_cr",
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
    return [r[1] for r in conn.execute(
        "PRAGMA table_info(fundamentals)")]

def _upsert(conn, vals):
    keys = list(vals.keys())
    ph = ", ".join("?" for _ in keys)
    conn.execute("DELETE FROM fundamentals WHERE symbol=?",
                 (vals["symbol"],))
    conn.execute(f"INSERT INTO fundamentals({', '.join(keys)}) "
                 f"VALUES({ph})", [vals[k] for k in keys])

def ingest_csv(path=CSV_PATH):
    if not os.path.exists(path):
        print(f"[FUND] no csv at {path}")
        return 0
    conn = db.get_conn()
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
            else:
                try:
                    vals[key] = float(
                        str(v).replace(",", "").replace("%", ""))
                except Exception:
                    continue
        if vals.get("symbol"):
            _upsert(conn, vals)
            n += 1
    conn.commit()
    conn.close()
    print(f"[FUND] ingested {n} rows from csv")
    return n

def refresh_yahoo(limit=100):
    import yfinance as yf
    conn = db.get_conn()
    table_cols = set(_table_cols(conn))
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM universe_broad "
        "ORDER BY mcap_cr DESC LIMIT ?", (limit,))]
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
        put("debt_eq", "debtToEquity", 0.01)
        put("promoter", "heldPercentInsiders", 100.0)
        put("roce", "returnOnEquity", 100.0)
        put("mcap_cr", "marketCap", 1e-7)

        if len(vals) > 1:
            _upsert(conn, vals)
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