"""Pre-2020 bhavcopy via the legacy cm<DD><MMM><YYYY>bhav.csv.zip archives.
sec_bhavdata_full only exists from ~2020; this fills 2016-2019 with the
same schema. No delivery data in the old format — deliv columns are NaN,
which the backtest never reads and the screener treats as no-spike.

Two archive generations (verified 2026-08-17): files from ~2011 onward
carry TOTALTRADES + ISIN; older ones (checked back to 2004) stop at
TOTTRDVAL. `trades` is NaN for the older generation — nothing in the
backtest reads it, and the screener treats NaN as no-spike.
"""
import io
from datetime import date

import numpy as np
import pandas as pd

import config
from ingest import nse

OLD_URL = ("https://nsearchives.nseindia.com/content/historical/EQUITIES/"
           "{yyyy}/{mon}/cm{ddmonyyyy}bhav.csv.zip")


def fetch(d: date) -> pd.DataFrame | None:
    url = OLD_URL.format(yyyy=d.strftime("%Y"), mon=d.strftime("%b").upper(),
                         ddmonyyyy=d.strftime("%d%b%Y").upper())
    r = nse.get(url, timeout=config.TIMEOUT)
    if r.status_code == 404:
        return None  # holiday / weekend
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content), compression="zip")
    df = df[df["SERIES"].isin(config.SERIES)].copy()
    out = pd.DataFrame({
        "symbol": df["SYMBOL"].str.strip(),
        "date": pd.to_datetime(d),
        "open": df["OPEN"], "high": df["HIGH"], "low": df["LOW"],
        "close": df["CLOSE"], "volume": df["TOTTRDQTY"].astype("float64"),
        "turnover_lacs": df["TOTTRDVAL"] / 1e5,   # rupees → lakhs, verified
        "trades": (df["TOTALTRADES"] if "TOTALTRADES" in df.columns
                   else np.nan),                  # absent pre-~2011
        "deliv_qty": np.nan, "deliv_pct": np.nan,
    })
    return out[["symbol", "date", "open", "high", "low", "close", "volume",
                "turnover_lacs", "trades", "deliv_qty", "deliv_pct"]]


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
