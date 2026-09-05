import datetime as dt
import io
import requests
import pandas as pd
import db

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9",
}

API_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
LOCAL_CSV = "data/nifty500_constituents.csv"

def pick(df, options):
    for opt in options:
        for col in df.columns:
            if col.strip().lower() == opt.lower():
                return col
    return None

def from_api():
    s = requests.Session()
    s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
    r = s.get(API_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    payload = r.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    out = []
    for row in rows:
        sym = row.get("symbol")
        meta = row.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        if sym and "NIFTY" not in str(sym):
            out.append((sym, meta.get("companyName"), meta.get("sector")))
    return out

def from_csv(source):
    if source.startswith("http"):
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
        r = s.get(source, headers=HEADERS, timeout=20)
        r.raise_for_status()
        text = r.text
    else:
        with open(source, "r", encoding="utf-8") as f:
            text = f.read()
    df = pd.read_csv(io.StringIO(text))
    sym_col = pick(df, ["Symbol"])
    if sym_col is None:
        raise ValueError("No Symbol column found")
    name_col = pick(df, ["Company Name", "Name"])
    sec_col = pick(df, ["Industry", "Sector"])
    out = []
    for _, r in df.iterrows():
        sym = str(r[sym_col]).strip()
        if not sym or "NIFTY" in sym.upper():
            continue
        out.append((sym, r[name_col] if name_col else None,
                    r[sec_col] if sec_col else None))
    return out

def main():
    rows = None
    sources = [
        ("local CSV file", lambda: from_csv(LOCAL_CSV)),
        ("NSE API", from_api),
        ("NSE archives CSV", lambda: from_csv(CSV_URL)),
    ]
    for label, fn in sources:
        try:
            rows = fn()
            if rows and len(rows) >= 400:
                print(f"Source used: {label} ({len(rows)} stocks)")
                break
        except Exception as e:
            print(f"{label} failed: {type(e).__name__}")

    if not rows or len(rows) < 400:
        print("ALL AUTOMATIC SOURCES FAILED. Tell me and we fix together.")
        return

    conn = db.get_conn()
    now = dt.datetime.now().isoformat()
    for sym, name, sector in rows:
        conn.execute(
            "INSERT INTO stocks(symbol,name,sector,active,updated_at) "
            "VALUES(?,?,?,1,?) ON CONFLICT(symbol) DO UPDATE SET "
            "name=excluded.name, sector=excluded.sector, "
            "updated_at=excluded.updated_at",
            (sym, name, sector, now))
    conn.commit()
    n = conn.execute(
        "SELECT COUNT(*) FROM stocks WHERE active=1").fetchone()[0]
    print(f"Universe loaded into database: {n} stocks")
    conn.close()

main()