"""sec_bhavdata_full: one CSV per trading day with OHLCV + delivery qty/%.
This single file is the backbone: prices AND the delivery footprint."""
import io
from datetime import date

import pandas as pd

import config
from ingest import nse

COLS = {
    "SYMBOL": "symbol", "SERIES": "series", "DATE1": "date",
    "OPEN_PRICE": "open", "HIGH_PRICE": "high", "LOW_PRICE": "low",
    "CLOSE_PRICE": "close", "TTL_TRD_QNTY": "volume",
    "TURNOVER_LACS": "turnover_lacs", "NO_OF_TRADES": "trades",
    "DELIV_QTY": "deliv_qty", "DELIV_PER": "deliv_pct",
}


def fetch(d: date) -> pd.DataFrame | None:
    url = config.BHAV_URL.format(ddmmyyyy=d.strftime("%d%m%Y"))
    r = nse.get(url, timeout=config.TIMEOUT)
    if r.status_code == 404:
        return None  # holiday / weekend
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=COLS)[list(COLS.values())]
    for c in df.select_dtypes("object"):
        df[c] = df[c].str.strip()
    df = df[df["series"].isin(config.SERIES)].copy()
    num = ["open", "high", "low", "close", "volume", "turnover_lacs",
           "trades", "deliv_qty", "deliv_pct"]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce")
    df["date"] = pd.to_datetime(d)
    return df.drop(columns=["series"])


def store(d: date) -> bool:
    out = config.DATA_DIR / "bhav" / f"{d.isoformat()}.parquet"
    if out.exists():
        return True
    df = fetch(d)
    if df is None or df.empty:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return True


def load_all() -> pd.DataFrame:
    files = sorted((config.DATA_DIR / "bhav").glob("*.parquet"))
    if not files:
        raise SystemExit("No bhavcopy data. Run backfill.py first.")
    df = pd.concat(map(pd.read_parquet, files), ignore_index=True)
    # canonicalize renamed tickers so histories merge (Tier 0 hygiene)
    from ingest import renames
    df["symbol"] = renames.canonical(df["symbol"])
    return df.drop_duplicates(subset=["date", "symbol"], keep="last")
