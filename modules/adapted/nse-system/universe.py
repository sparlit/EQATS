import csv
import datetime
import io

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9",
}

API_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20500"
CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
LOCAL_CSV = "data/nifty500_constituents.csv"


def pick(columns, options):
    for opt in options:
        for col in columns:
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
        with open(source, encoding="utf-8") as f:
            text = f.read()
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    sym_col = pick(fieldnames, ["Symbol"])
    if sym_col is None:
        msg = "No Symbol column found"
        raise ValueError(msg)
    name_col = pick(fieldnames, ["Company Name", "Name"])
    sec_col = pick(fieldnames, ["Industry", "Sector"])
    out = []
    for row in reader:
        sym = str(row[sym_col]).strip()
        if not sym or "NIFTY" in sym.upper():
            continue
        out.append((sym, row[name_col] if name_col else None, row[sec_col] if sec_col else None))
    return out


def main():
    rows = None
    sources = [
        ("local CSV file", lambda: from_csv(LOCAL_CSV)),
        ("NSE API", from_api),
    ]
    for name, fn in sources:
        try:
            rows = fn()
            if rows:
                print(f"Loaded {len(rows)} symbols from {name}")
                break
        except Exception as e:
            print(f"Failed to load from {name}: {e}")
    if not rows:
        msg = "All sources failed"
        raise RuntimeError(msg)
    return rows


if __name__ == "__main__":
    main()
