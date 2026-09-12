import datetime
import io

import pytz
import requests

try:
    import pandas as pd
except ImportError:
    pd = None

import db


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    else:
        if dt.tzinfo is None:
            dt = ist.localize(dt)
        now = dt.astimezone(ist)
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
    if pd is None:
        msg = "pandas is required for CSV processing"
        raise ImportError(msg)
    if source.startswith("http"):
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=HEADERS, timeout=15)
        r = s.get(source, headers=HEADERS, timeout=20)
        r.raise_for_status()
        text = r.text
    else:
        with open(source, encoding="utf-8") as f:
            text = f.read()
    df = pd.read_csv(io.StringIO(text))
    sym_col = pick(df, ["Symbol"])
    if sym_col is None:
        msg = "No Symbol column found"
        raise ValueError(msg)
    name_col = pick(df, ["Company Name", "Name"])
    sec_col = pick(df, ["Industry", "Sector"])
    out = []
    for _, r in df.iterrows():
        sym = str(r[sym_col]).strip()
        if not sym or "NIFTY" in sym.upper():
            continue
        out.append((sym, r[name_col] if name_col else None, r[sec_col] if sec_col else None))
    return out


def main():
    rows = None
    sources = [
        ("local CSV file", lambda: from_csv(LOCAL_CSV)),
        ("NSE API", from_api),
        ("NSE CSV archive", lambda: from_csv(CSV_URL)),
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
        print("No data loaded from any source")
        return
    for sym, name, sector in rows[:10]:
        print(f"{sym}: {name} ({sector})")


if __name__ == "__main__":
    main()
