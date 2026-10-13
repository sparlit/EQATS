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


import glob

import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"
prices_path = f"{BASE}/data/prices.parquet"
uni_paths = sorted(glob.glob(f"{BASE}/universe/universe_*.parquet"))
uni_path = uni_paths[-1]  # latest

print("=" * 60)
print("PRICES:", prices_path)
px = pd.read_parquet(prices_path)
print("shape:", px.shape)
print("columns/dtypes:\n", px.dtypes)
px["date"] = pd.to_datetime(px["date"])
print("date range:", px["date"].min().date(), "->", px["date"].max().date())
print("n symbols:", px["symbol"].nunique())
print("null close:", int(px["close"].isna().sum()))
print("null volume:", int(px["volume"].isna().sum()))

# duplicate (symbol,date) check
dups = px.duplicated(subset=["symbol", "date"]).sum()
print("duplicate (symbol,date) rows:", int(dups))

# per-symbol row counts
rc = px.groupby("symbol").size()
print("rows/symbol: min=%d median=%d max=%d" % (rc.min(), int(rc.median()), rc.max()))
print("symbols with <253 rows:", int((rc < 253).sum()))


# is each symbol sorted by date?
def is_sorted(g):
    return g["date"].is_monotonic_increasing


sorted_flags = px.sort_values(["symbol", "date"]).groupby("symbol").apply(is_sorted)
print("symbols NOT sorted by date:", int((~sorted_flags).sum()))

print("=" * 60)
print("UNIVERSE:", uni_path)
uni = pd.read_parquet(uni_path)
print("shape:", uni.shape)
print("columns/dtypes:\n", uni.dtypes)
print("n symbols:", uni["symbol"].nunique())
print("in_universe == True:", int(uni["in_universe"].sum()))

# symbol overlap
ps, us = set(px["symbol"]), set(uni["symbol"])
print("in prices not universe:", len(ps - us))
print("in universe not prices:", len(us - ps))
print("=" * 60)
