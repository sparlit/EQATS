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


"""
Compare a fresh pipeline output against a previously-saved verified
snapshot, column by column, all symbols.
"""
import pandas as pd

OLD_PATH = "/home/ec2-user/nse-factor-engine/manual_backups/momentum_signals_final_30062026_verified_103859.parquet"
NEW_PATH = "/home/ec2-user/nse-factor-engine/signals/final/momentum_signals_final_30062026.parquet"

old = pd.read_parquet(OLD_PATH)
new = pd.read_parquet(NEW_PATH)

print(f"OLD shape: {old.shape}")
print(f"NEW shape: {new.shape}")

old_cols = set(old.columns)
new_cols = set(new.columns)
print(f"\nColumns only in OLD: {old_cols - new_cols}")
print(f"Columns only in NEW: {new_cols - old_cols}")

old_symbols = set(old["symbol"])
new_symbols = set(new["symbol"])
print(f"\nSymbols only in OLD: {old_symbols - new_symbols}")
print(f"Symbols only in NEW: {new_symbols - old_symbols}")

common_cols = sorted(old_cols & new_cols - {"symbol"})
merged = old.merge(new, on="symbol", suffixes=("_old", "_new"), how="inner")

print(f"\nComparing {len(common_cols)} common columns across {len(merged)} common symbols...\n")

any_diff = False
for col in common_cols:
    old_col = merged[f"{col}_old"]
    new_col = merged[f"{col}_new"]

    if pd.api.types.is_numeric_dtype(old_col) and pd.api.types.is_numeric_dtype(new_col):
        both_nan = old_col.isna() & new_col.isna()
        diff_mask = ~both_nan & (
            ~(old_col == new_col) if old_col.dtype == bool else ~((old_col - new_col).abs() < 1e-9)
        )
        diff_mask = diff_mask.fillna(True)
    else:
        both_nan = old_col.isna() & new_col.isna()
        diff_mask = ~both_nan & (old_col.astype(str) != new_col.astype(str))

    n_diff = diff_mask.sum()
    if n_diff > 0:
        any_diff = True
        print(f"COLUMN CHANGED: {col} — {n_diff} symbol(s) differ")
        sample = merged[diff_mask][["symbol", f"{col}_old", f"{col}_new"]].head(10)
        print(sample.to_string(index=False))
        print()

if not any_diff:
    print("RESULT: No differences found in any common column for any common symbol.")
else:
    print("RESULT: Differences found (see above).")
