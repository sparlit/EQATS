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

BASE = "/home/ec2-user/nse-factor-engine"
px = pd.read_parquet(f"{BASE}/data/prices.parquet")
px["date"] = pd.to_datetime(px["date"])
px = px.sort_values(["symbol", "date"]).reset_index(drop=True)

# ffill null close
px["close"] = px.groupby("symbol")["close"].ffill()

date_counts = px.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()

# --- compute returns ---
records = []
for sym, grp in px.groupby("symbol"):
    dates = grp["date"].sort_values().reset_index(drop=True)
    closes = grp.set_index("date")["close"].sort_index()
    n = len(dates)

    T_pos = dates[dates == T].index
    T_pos_i = T_pos[0] if len(T_pos) > 0 else n - 1

    def get_close(offset):
        idx = T_pos_i - offset
        if idx < 0:
            return np.nan
        d = dates.iloc[idx]
        return closes.loc[d]

    c_t21 = get_close(21)
    c_t63 = get_close(63)
    c_t126 = get_close(126)
    c_t252 = get_close(252)

    def ret(end, start):
        if pd.isna(end) or pd.isna(start) or start == 0:
            return np.nan
        return (end - start) / start

    records.append(
        {
            "symbol": sym,
            "ret_12m1m": ret(c_t21, c_t252),
            "ret_6m1m": ret(c_t21, c_t126),
            "ret_3m1m": ret(c_t21, c_t63),
        }
    )

df = pd.DataFrame(records)

# --- sanity checks ---
print(f"Rows: {len(df)}  |  Columns: {list(df.columns)}")
print("\nNaN counts:")
print(df[["ret_12m1m", "ret_6m1m", "ret_3m1m"]].isna().sum().to_string())

print("\nDescriptive stats:")
print(df[["ret_12m1m", "ret_6m1m", "ret_3m1m"]].describe().round(4).to_string())

print("\nSample — 5 symbols with all returns valid:")
print(df.dropna().head(5).to_string(index=False))

print("\nSample — symbols with partial NaN:")
partial = df[df.isna().any(axis=1)]
print(f"  count: {len(partial)}")
print(partial.head(5).to_string(index=False))
