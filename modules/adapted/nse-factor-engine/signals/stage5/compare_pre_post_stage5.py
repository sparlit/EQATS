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
Compare the original pre-Stage-5 (38-col) backup against the current
post-Stage-5 (49-col) final file, to show what Stage 5 actually added.
"""
import pandas as pd

OLD_PATH = "/home/ec2-user/nse-factor-engine/signals/final/momentum_signals_final_30062026_pre_stage5_backup.parquet"
NEW_PATH = "/home/ec2-user/nse-factor-engine/signals/final/momentum_signals_final_30062026.parquet"

old = pd.read_parquet(OLD_PATH)
new = pd.read_parquet(NEW_PATH)

print(f"PRE-STAGE-5 (backup) shape: {old.shape}")
print(f"POST-STAGE-5 (current)  shape: {new.shape}")

old_cols = set(old.columns)
new_cols = set(new.columns)
added_cols = new_cols - old_cols
removed_cols = old_cols - new_cols

print(f"\nColumns ADDED by Stage 5 ({len(added_cols)}): {sorted(added_cols)}")
print(f"Columns REMOVED ({len(removed_cols)}): {sorted(removed_cols)}")

old_symbols = set(old["symbol"])
new_symbols = set(new["symbol"])
print(f"\nSymbols only in pre-Stage-5: {old_symbols - new_symbols}")
print(f"Symbols only in post-Stage-5: {new_symbols - old_symbols}")
print(
    f"Row count: pre={len(old)}, post={len(new)} (expect equal -- non-investable retained, not dropped)"
)

common_cols = sorted(old_cols & new_cols - {"symbol"})
merged = old.merge(new, on="symbol", suffixes=("_old", "_new"), how="inner")

print(f"\nChecking {len(common_cols)} pre-existing columns for unintended changes...\n")
any_diff = False
for col in common_cols:
    o = merged[f"{col}_old"]
    n = merged[f"{col}_new"]
    if pd.api.types.is_bool_dtype(o) or pd.api.types.is_bool_dtype(n):
        both_nan = o.isna() & n.isna()
        diff_mask = ~both_nan & (o.astype("boolean") != n.astype("boolean"))
        diff_mask = diff_mask.fillna(True)
    elif pd.api.types.is_numeric_dtype(o) and pd.api.types.is_numeric_dtype(n):
        both_nan = o.isna() & n.isna()
        diff_mask = ~both_nan & ~((o - n).abs() < 1e-9)
        diff_mask = diff_mask.fillna(True)
    else:
        both_nan = o.isna() & n.isna()
        diff_mask = ~both_nan & (o.astype(str) != n.astype(str))
    n_diff = diff_mask.sum()
    if n_diff > 0:
        any_diff = True
        print(f"UNEXPECTED CHANGE: {col} — {n_diff} symbols differ")

if not any_diff:
    print("Confirmed: all pre-existing (Stage 2-4) column values unchanged.")

print("\n--- Sample: 5 in-universe symbols, new Stage 5 columns ---")
sample = new[new["in_universe"]][["symbol"] + sorted(added_cols)].head(5)
print(sample.to_string(index=False))

print("\n--- Sample: 2 excluded (in_universe=False) symbols ---")
excluded = new[not new["in_universe"]][["symbol"] + sorted(added_cols)].head(2)
print(excluded.to_string(index=False))
