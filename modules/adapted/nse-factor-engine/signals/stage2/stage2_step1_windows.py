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

# --- forward-fill null close within symbol, log it ---
null_mask = px["close"].isna()
if null_mask.any():
    affected = px.loc[null_mask, "symbol"].unique().tolist()
    print(f"[ffill] null close in symbols: {affected}")
    px["close"] = px.groupby("symbol")["close"].ffill()
    remaining = px["close"].isna().sum()
    print(f"[ffill] null close remaining after ffill: {remaining}")
else:
    print("[ffill] no null closes found")

# --- anchor T ---
date_counts = px.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()
print(f"\nT (as-of date): {T.date()}")

# --- per-symbol: resolve window offsets to dates ---
OFFSETS = {"T-252": 252, "T-231": 231, "T-126": 126, "T-63": 63, "T-21": 21}

records = []
for sym, grp in px.groupby("symbol"):
    dates = grp["date"].sort_values().reset_index(drop=True)
    n = len(dates)
    # find position of T in this symbol's date index
    T_pos = dates[dates == T].index
    if len(T_pos) == 0:
        # symbol doesn't have T — use its own last date
        T_pos_i = n - 1
    else:
        T_pos_i = T_pos[0]

    row = {"symbol": sym, "n_rows": n, "T_pos": T_pos_i}
    for label, offset in OFFSETS.items():
        idx = T_pos_i - offset
        row[label] = dates.iloc[idx].date() if idx >= 0 else None
    records.append(row)

df = pd.DataFrame(records)

# --- summary ---
print(f"\nSymbols with all 5 windows valid: {df[df['T-252'].notna()].shape[0]}")
print(f"Symbols missing T-252 (12M window invalid): {df['T-252'].isna().sum()}")
print(f"Symbols missing T-231 (vol_231 / composites invalid): {df['T-231'].isna().sum()}")
print(f"Symbols missing T-126 (6M window invalid): {df['T-126'].isna().sum()}")
print(f"Symbols missing T-63  (3M window invalid): {df['T-63'].isna().sum()}")
print(f"Symbols missing T-21  (skip-month anchor invalid): {df['T-21'].isna().sum()}")

# --- spot-check: print window dates for 3 symbols ---
sample = df[df["T-252"].notna()].head(3)
print("\nSpot-check (3 symbols with full windows):")
print(sample[["symbol", "n_rows", "T-252", "T-231", "T-126", "T-63", "T-21", "T_pos"]].to_string(index=False))

# --- also flag symbols where T-21 is None (can't compute any return) ---
no_t21 = df[df["T-21"].isna()]["symbol"].tolist()
if no_t21:
    print(f"\nSymbols with <21 rows (no signal computable): {no_t21}")
else:
    print("\nAll symbols have >=21 rows — T-21 anchor valid for all")
