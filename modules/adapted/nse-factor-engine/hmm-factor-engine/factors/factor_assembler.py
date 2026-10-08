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


# Part 5: Assemble all 8 factor return series into one aligned parquet

import os

import numpy as np
import pandas as pd

BASE_DIR = "/home/ec2-user/nse-factor-engine/hmm-factor-engine"
DATA_DIR = os.path.join(BASE_DIR, "factors", "data")
OUT_FILE = os.path.join(DATA_DIR, "factor_assembler_output.parquet")

FACTORS = [
    ("mom", "mom_returns.parquet", "long_return"),
    ("lowvol", "lowvol_returns.parquet", "long_return"),
    ("bab", "bab_returns.parquet", "long_return"),
    ("rmw_roe", "rmw_roe_returns.parquet", "long_return"),
    ("rmw_op_roe", "rmw_op_roe_returns.parquet", "long_return"),
    ("quality", "quality_returns.parquet", "long_return"),
    ("value", "value_returns.parquet", "long_return"),
    ("size", "size_returns.parquet", "long_return"),
]

IS_SPLITS = {
    "mom": ("2014-01", "2023-05"),
    "lowvol": ("2014-01", "2023-05"),
    "bab": ("2016-01", "2023-05"),
    "rmw_roe": ("2018-07", "2023-05"),
    "rmw_op_roe": ("2018-07", "2023-05"),
    "quality": ("2020-07", "2024-05"),
    "value": ("2018-07", "2023-05"),
    "size": ("2018-07", "2023-05"),
}

# ── Load & align ─────────────────────────────────────────────────────────────
series = {}
for short, fname, col in FACTORS:
    df = pd.read_parquet(os.path.join(DATA_DIR, fname))
    df.index = pd.to_datetime(df.index).to_period("M")
    series[short] = df[col].rename(short)

combined = pd.concat(series.values(), axis=1, join="outer").sort_index()
combined.index.name = "date"

print(f"Common window   : {combined.index[0]} → {combined.index[-1]}")
print(f"Months (inner)  : {combined.shape[0]}")
print(f"Factors         : {list(combined.columns)}")
print(f"Nulls per factor:\n{combined.isna().sum().to_string()}")

# ── Per-factor stats on full available history ────────────────────────────────
print("\n--- Per-factor stats (full history) ---")
print(f"  {'Factor':<12} {'Months':>7} {'Ann Ret':>9} {'Sharpe':>8} {'Start':<10} {'End'}")
print(f"  {'-' * 12} {'-' * 7} {'-' * 9} {'-' * 8} {'-' * 10} {'-' * 10}")
for short, fname, col in FACTORS:
    s = series[short].dropna()
    ann_ret = s.mean() * 12 * 100
    sharpe = (s.mean() / s.std()) * np.sqrt(12)
    print(
        f"  {short:<12} {len(s):>7} {ann_ret:>+8.2f}% {sharpe:>+8.3f} {str(s.index[0]):<10} {str(s.index[-1])}"
    )

# ── IS vs OOS stats ───────────────────────────────────────────────────────────
print("\n--- IS vs OOS stats ---")
print(f"  {'Factor':<12} {'IS Sharpe':>10} {'OOS Sharpe':>11} {'IS Months':>10} {'OOS Months':>11}")
print(f"  {'-' * 12} {'-' * 10} {'-' * 11} {'-' * 10} {'-' * 11}")
for short, fname, col in FACTORS:
    s = series[short].dropna()
    is_s, is_e = IS_SPLITS[short]
    is_data = s[(s.index >= pd.Period(is_s, "M")) & (s.index <= pd.Period(is_e, "M"))]
    oos_data = s[s.index > pd.Period(is_e, "M")]
    is_sharpe = (is_data.mean() / is_data.std()) * np.sqrt(12) if len(is_data) > 1 else np.nan
    oos_sharpe = (oos_data.mean() / oos_data.std()) * np.sqrt(12) if len(oos_data) > 1 else np.nan
    print(
        f"  {short:<12} {is_sharpe:>+10.3f} {oos_sharpe:>+11.3f} {len(is_data):>10} {len(oos_data):>11}"
    )

# ── Correlation matrix (common window = inner join) ───────────────────────────
print("\n--- Correlation matrix (common window) ---")
pd.set_option("display.float_format", "{:+.2f}".format)
pd.set_option("display.width", 120)
print(combined.corr().to_string())

# ── Save ─────────────────────────────────────────────────────────────────────
combined.to_parquet(OUT_FILE)
print(f"\nSaved → {OUT_FILE}")
print(f"Shape : {combined.shape}")
