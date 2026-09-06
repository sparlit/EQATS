"""Daily bulk + block deal files. These name the buyer/seller — the only
public feed where you see specific large hands in specific stocks same-day.
Caveat: a bulk deal is often just one fund selling to another; it's a flag,
not a signal by itself."""
import io
from datetime import date

import pandas as pd

import config
from ingest import nse


def _fetch(url: str, kind: str) -> pd.DataFrame:
    r = nse.get(url, timeout=config.TIMEOUT)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip().lower().replace(" ", "_").replace("/", "_")
                  for c in df.columns]
    df["kind"] = kind
    return df


def store(d: date) -> None:
    """bulk.csv/block.csv hold the latest trading day's deals. Run daily;
    the parquet name is stamped with the date inside the file itself."""
    frames = []
    for url, kind in ((config.BULK_URL, "bulk"), (config.BLOCK_URL, "block")):
        try:
            frames.append(_fetch(url, kind))
        except Exception as e:
            print(f"  {kind} deals failed: {e}")
    if not frames:
        return
    df = pd.concat(frames, ignore_index=True)
    out = config.DATA_DIR / "deals" / f"{d.isoformat()}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)


def load_all() -> pd.DataFrame | None:
    files = sorted((config.DATA_DIR / "deals").glob("*.parquet"))
    if not files:
        return None
    return pd.concat(map(pd.read_parquet, files), ignore_index=True)
