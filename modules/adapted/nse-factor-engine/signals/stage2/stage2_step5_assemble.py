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


import os

import numpy as np
import pandas as pd

BASE = "/home/ec2-user/nse-factor-engine"
RF = 0.07  # Indian 10Y G-Sec constant — placeholder until Stage 6 G-Sec time series

DATA_QUALITY_FLAGS = {"VEDL": "KI-001: missing split adjustment 2026-04-30"}

# --- load prices ---
px = pd.read_parquet(f"{BASE}/data/prices.parquet")
px["date"] = pd.to_datetime(px["date"])
px = px.sort_values(["symbol", "date"]).reset_index(drop=True)
px["close"] = px.groupby("symbol")["close"].ffill()
date_counts = px.groupby("date")["symbol"].count()
T = date_counts[date_counts >= 490].index.max()


# --- helpers ---
def realised_vol(lr, ddof=1):
    return np.std(lr, ddof=ddof) * np.sqrt(252) if len(lr) >= ddof + 1 else np.nan


def downside_vol(lr, ddof=1):
    neg = lr[lr < 0]
    return np.std(neg, ddof=ddof) * np.sqrt(252) if len(neg) >= ddof + 1 else np.nan


def safe_div(num, den):
    return num / den if not (pd.isna(num) or pd.isna(den) or den == 0) else np.nan


def pct_ret(end, start):
    return (end - start) / start if not (pd.isna(end) or pd.isna(start) or start == 0) else np.nan


# --- compute all signals ---
records = []
for sym, grp in px.groupby("symbol"):
    dates = grp["date"].sort_values().reset_index(drop=True)
    closes = grp.sort_values("date")["close"].reset_index(drop=True)
    n = len(dates)

    T_pos = dates[dates == T].index
    T_pos_i = T_pos[0] if len(T_pos) > 0 else n - 1

    def get_close(offset):
        idx = T_pos_i - offset
        return closes.iloc[idx] if idx >= 0 else np.nan

    # returns
    ret_12m1m = pct_ret(get_close(21), get_close(252))
    ret_6m1m = pct_ret(get_close(21), get_close(126))
    ret_3m1m = pct_ret(get_close(21), get_close(63))

    # vol_252: T-252 → T
    s252 = T_pos_i - 252
    if s252 >= 0:
        sl = closes.iloc[s252 : T_pos_i + 1]
        lr = np.log(sl.values[1:] / sl.values[:-1])
        v_252 = realised_vol(lr)
        dv_252 = downside_vol(lr)
    else:
        v_252 = dv_252 = np.nan

    # vol_231: T-252 → T-21
    s231, e231 = T_pos_i - 252, T_pos_i - 21
    if s231 >= 0 and e231 > s231:
        sl = closes.iloc[s231 : e231 + 1]
        lr = np.log(sl.values[1:] / sl.values[:-1])
        v_231 = realised_vol(lr)
        dv_231 = downside_vol(lr)
    else:
        v_231 = dv_231 = np.nan

    # composites
    vol_adj_ret = safe_div(ret_12m1m, v_231)
    sharpe_style = safe_div(ret_12m1m - RF, v_231)
    sortino_style = safe_div(ret_12m1m - RF, dv_231)  # EXTENSION: per-stock Sortino

    records.append(
        {
            "symbol": sym,
            "as_of_date": T.date(),
            "ret_12m1m": ret_12m1m,
            "ret_6m1m": ret_6m1m,
            "ret_3m1m": ret_3m1m,
            "vol_252": v_252,
            "vol_231": v_231,
            "downside_vol_252": dv_252,
            "downside_vol_231": dv_231,
            "simple_vol_adj_momentum": vol_adj_ret,
            "sharpe_style_momentum": sharpe_style,
            "sortino_style_momentum": sortino_style,
            "data_quality_flag": DATA_QUALITY_FLAGS.get(sym, ""),
        }
    )

df = pd.DataFrame(records)

# --- write output ---
import zoneinfo
from datetime import datetime as _dt

_run_date_ist = _dt.now(zoneinfo.ZoneInfo("Asia/Kolkata")).date()
date_str = _run_date_ist.strftime("%d%m%Y")  # RUN DATE, not T -- see METHODOLOGY.md
out_path = f"{BASE}/signals/stage2/momentum_core_signals_{date_str}.parquet"
df.to_parquet(out_path, index=False)

# --- final summary ---
print("=" * 60)
print("Stage 2 — Momentum Core Signals")
print(f"As-of date  : {T.date()}")
print(f"Output      : {out_path}")
print(f"File size   : {os.path.getsize(out_path):,} bytes")
print("=" * 60)

print(f"\nShape       : {df.shape}")
print(f"Columns     : {list(df.columns)}")

print("\nNaN counts:")
sig_cols = [
    "ret_12m1m",
    "ret_6m1m",
    "ret_3m1m",
    "vol_252",
    "vol_231",
    "downside_vol_252",
    "downside_vol_231",
    "simple_vol_adj_momentum",
    "sharpe_style_momentum",
    "sortino_style_momentum",
]
print(df[sig_cols].isna().sum().to_string())

print("\nData quality flags:")
flagged = df[df["data_quality_flag"] != ""]
print(f"  Flagged symbols : {len(flagged)}")
for _, row in flagged.iterrows():
    print(f"  {row['symbol']:12s} → {row['data_quality_flag']}")

print("\nTop 10 by vol_adj_ret (all symbols, NaN excluded):")
top = (
    df.dropna(subset=["simple_vol_adj_momentum"])
    .sort_values("simple_vol_adj_momentum", ascending=False)
    .head(10)
)
print(
    top[
        [
            "symbol",
            "ret_12m1m",
            "vol_231",
            "simple_vol_adj_momentum",
            "sharpe_style_momentum",
            "sortino_style_momentum",
        ]
    ].to_string(index=False)
)

print("\nBottom 5 by vol_adj_ret (all symbols, NaN excluded):")
bot = df.dropna(subset=["simple_vol_adj_momentum"]).sort_values("simple_vol_adj_momentum").head(5)
print(
    bot[
        [
            "symbol",
            "ret_12m1m",
            "vol_231",
            "simple_vol_adj_momentum",
            "sharpe_style_momentum",
            "sortino_style_momentum",
        ]
    ].to_string(index=False)
)

print("\n" + "=" * 60)
print("Stage 2 complete. in_universe merge deferred to Stage 4.")
print("=" * 60)
