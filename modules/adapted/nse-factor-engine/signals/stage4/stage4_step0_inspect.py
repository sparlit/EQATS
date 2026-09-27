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


import numpy as np
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine/"

prices = pd.read_parquet(BASE + "data/prices.parquet")
universe_meta = pd.read_parquet(BASE + "data/universe_metadata.parquet")
signals = pd.read_parquet(BASE + "signals/final/momentum_signals_final_25062026.parquet")

print("=" * 60)
print("PRICES")
print("=" * 60)
print("shape:", prices.shape)
print("dtypes:\n", prices.dtypes)
print("date range:", prices["date"].min(), "->", prices["date"].max())
print("n symbols:", prices["symbol"].nunique())
print("nulls:\n", prices.isnull().sum())
print("dupes (symbol,date):", prices.duplicated(subset=["symbol", "date"]).sum())

print()
print("=" * 60)
print("T RESOLUTION (robust method)")
print("=" * 60)
date_counts = prices.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
all_dates = sorted(prices[prices["date"] <= T]["date"].unique())
T_21 = all_dates[-22]
T_252 = all_dates[-253]
print("T:", T, "| symbols on T:", date_counts[T])
print("T_21:", T_21)
print("T_252:", T_252)
print("total trading days available <= T:", len(all_dates))

print()
print("=" * 60)
print("VOLUME SANITY")
print("=" * 60)
print("volume dtype:", prices["volume"].dtype)
print("volume <= 0 rows:", (prices["volume"] <= 0).sum())
print("volume null rows:", prices["volume"].isnull().sum())
vol_by_symbol_count = prices.groupby("symbol")["volume"].apply(lambda x: (x <= 0).sum())
print("symbols with any zero/neg volume:", (vol_by_symbol_count > 0).sum())
print("top 5 symbols by zero/neg volume day count:\n", vol_by_symbol_count.sort_values(ascending=False).head())

print()
print("=" * 60)
print("PRICE SANITY (OHLC)")
print("=" * 60)
bad_hl = prices[prices["high"] < prices["low"]]
print("rows where high < low:", len(bad_hl))
all_nan_rows = prices[prices[["open", "high", "low", "close", "volume"]].isnull().all(axis=1)]
print("fully-NaN OHLCV rows:", len(all_nan_rows))
print(all_nan_rows[["symbol", "date"]] if len(all_nan_rows) else "none")

print()
print("=" * 60)
print("SIGNALS FILE (stage4 starting point)")
print("=" * 60)
print("shape:", signals.shape)
print("columns:", list(signals.columns))
print("nulls per column:\n", signals.isnull().sum())
print("as_of_date unique:", signals["as_of_date"].unique() if "as_of_date" in signals.columns else "no as_of_date col")

print()
print("=" * 60)
print("UNIVERSE METADATA")
print("=" * 60)
print("shape:", universe_meta.shape)
print("columns:", list(universe_meta.columns))
print("null industry count:", universe_meta["industry"].isnull().sum())

print()
print("=" * 60)
print("SYMBOL ALIGNMENT")
print("=" * 60)
print("prices symbols not in signals:", set(prices["symbol"].unique()) - set(signals["symbol"].unique()))
print("signals symbols not in prices:", set(signals["symbol"].unique()) - set(prices["symbol"].unique()))
