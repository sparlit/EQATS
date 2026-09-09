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


"""Symbol-rename canonicalization (Tier 0 hygiene).

NSE's symbolchange.csv maps old→new tickers. Without it, a renamed stock
looks like a delisting (position force-exited) and its history splits
into two unrelated columns — corrupting momentum lookbacks for every
renamed name. canonical() rewrites any symbol series to the FINAL name,
resolving chains (A→B→C).

    python -m ingest.renames      # refresh data/symbolchange.parquet
"""
import io

import pandas as pd
from ingest import nse

import config

URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
OUT = config.DATA_DIR / "symbolchange.parquet"
_map_cache: dict | None = None


def refresh() -> pd.DataFrame:
    r = nse.get(URL, timeout=config.TIMEOUT)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), encoding="latin-1", header=None, names=["company", "old", "new", "date"])
    for c in ("old", "new"):
        df[c] = df[c].astype(str).str.strip()
    df = df[(df["old"] != df["new"]) & (df["old"] != "") & (df["new"] != "")]
    df.to_parquet(OUT, index=False)
    return df


def mapping() -> dict:
    """old → final symbol, chains resolved."""
    global _map_cache
    if _map_cache is not None:
        return _map_cache
    if not OUT.exists():
        refresh()
    df = pd.read_parquet(OUT)
    m = dict(zip(df["old"], df["new"], strict=False))
    resolved = {}
    for old in m:
        cur, seen = old, set()
        while cur in m and cur not in seen:  # walk chains, stop cycles
            seen.add(cur)
            cur = m[cur]
        resolved[old] = cur
    _map_cache = resolved
    return resolved


def canonical(symbols: pd.Series) -> pd.Series:
    m = mapping()
    return symbols.map(lambda s: m.get(s, s))


if __name__ == "__main__":
    df = refresh()
    print(f"{len(df)} rename records; {len(mapping())} resolved mappings")
