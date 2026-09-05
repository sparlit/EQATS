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

import config
from ingest import nse

URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"
OUT = config.DATA_DIR / "symbolchange.parquet"
_map_cache: dict | None = None


def refresh() -> pd.DataFrame:
    r = nse.get(URL, timeout=config.TIMEOUT)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), encoding="latin-1", header=None,
                     names=["company", "old", "new", "date"])
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
    m = dict(zip(df["old"], df["new"]))
    resolved = {}
    for old in m:
        cur, seen = old, set()
        while cur in m and cur not in seen:      # walk chains, stop cycles
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
