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


from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PRICES_PATH = Path("data/prices.parquet")
METADATA_PATH = Path("data/universe_metadata.parquet")
LOG_PATH = Path("logs/data_quality.log")

# ── Load data ─────────────────────────────────────
prices = pd.read_parquet(PRICES_PATH)
prices["date"] = pd.to_datetime(prices["date"])
meta = pd.read_parquet(METADATA_PATH)

lines = []


def log(msg=""):
    print(msg)
    lines.append(msg)


# ── Report ────────────────────────────────────────
log("=" * 60)
log("DATA QUALITY REPORT")
log(f"Run Date : {date.today()}")
log(f"Prices   : {prices.shape[0]} rows | {prices.symbol.nunique()} symbols")
log(f"Metadata : {meta.shape[0]} rows")
log("=" * 60)

# 1. Duplicates
dupes = prices.duplicated(subset=["symbol", "date"]).sum()
log("\n[1] DUPLICATES")
log(f"    Duplicate symbol+date rows : {dupes}")

# 2. Missing OHLCV
log("\n[2] MISSING VALUES")
nulls = prices[["open", "high", "low", "close", "volume"]].isnull().sum()
for col, n in nulls.items():
    flag = " *** " if n > 0 else ""
    log(f"    {col:10s} : {n}{flag}")

# 3. Zero values
log("\n[3] ZERO VALUES")
for col in ["open", "high", "low", "close", "volume"]:
    n = (prices[col] == 0).sum()
    flag = " *** " if n > 0 else ""
    log(f"    {col:10s} : {n}{flag}")

# 4. Price sanity
log("\n[4] PRICE SANITY")
hl = (prices["high"] < prices["low"]).sum()
ch = (prices["close"] > prices["high"]).sum()
cl = (prices["close"] < prices["low"]).sum()
log(f"    high < low          : {hl}{' ***' if hl > 0 else ''}")
log(f"    close > high        : {ch}{' ***' if ch > 0 else ''}")
log(f"    close < low         : {cl}{' ***' if cl > 0 else ''}")

if hl > 0 or ch > 0 or cl > 0:
    bad = prices[
        (prices["high"] < prices["low"]) | (prices["close"] > prices["high"]) | (prices["close"] < prices["low"])
    ]
    log("\n    Offending rows:")
    log(bad[["symbol", "date", "open", "high", "low", "close"]].to_string(index=False))

# 5. Volume outliers
log("\n[5] VOLUME OUTLIERS (> 100x symbol average)")
avg_vol = prices.groupby("symbol")["volume"].transform("mean")
outliers = prices[prices["volume"] > 100 * avg_vol]
log(f"    Count               : {len(outliers)}")
if len(outliers) > 0:
    log(outliers[["symbol", "date", "volume"]].to_string(index=False))

# 6. Symbols with old end date
log("\n[6] SYMBOLS WITH STALE END DATE (> 30 days behind latest)")
latest = prices.date.max()
last_dates = prices.groupby("symbol")["date"].max()
stale = last_dates[last_dates < latest - pd.Timedelta(days=30)].sort_values()
log(f"    Count               : {len(stale)}")
if len(stale) > 0:
    log(stale.to_string())

# 7. Short history
log("\n[7] SYMBOLS WITH SHORT HISTORY (< 252 trading days)")
row_counts = prices.groupby("symbol")["date"].count()
short = row_counts[row_counts < 252].sort_values()
log(f"    Count               : {len(short)}")
if len(short) > 0:
    log(short.to_string())

# 8. Metadata completeness
log("\n[8] METADATA COMPLETENESS")
for col in ["company_name", "industry", "market_cap_cr"]:
    n = meta[col].isnull().sum()
    flag = " ***" if n > 0 else ""
    log(f"    {col:20s} missing : {n}{flag}")

# 9. Symbols in prices but not in metadata
log("\n[9] SYMBOL ALIGNMENT")
in_prices = set(prices.symbol.unique())
in_meta = set(meta.symbol.unique())
only_prices = in_prices - in_meta
only_meta = in_meta - in_prices
log(f"    In prices not in metadata : {len(only_prices)}")
if only_prices:
    log(f"    {sorted(only_prices)}")
log(f"    In metadata not in prices : {len(only_meta)}")
if only_meta:
    log(f"    {sorted(only_meta)}")

log("\n" + "=" * 60)
log("END OF REPORT")
log("=" * 60)

# ── Save to log ───────────────────────────────────
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(LOG_PATH, "w") as f:
    f.write("\n".join(lines))

print(f"\nReport saved to {LOG_PATH}")
