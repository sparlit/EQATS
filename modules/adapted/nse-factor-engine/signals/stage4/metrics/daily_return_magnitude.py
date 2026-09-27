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
Stage 4 — Absolute Daily Return Magnitude (Lottery Classifier)
Gray: high average daily move = lottery characteristic. Penalise erratic movers.

Bucket-count classifier over a 63 trading-day window, based on SIMPLE daily
returns (close[t]/close[t-1] - 1), not log returns.

Window: (T-63, T] in return-space -> requires close prices from T-64 through
T (64 closes -> 63 daily returns).

Buckets (count of days where |daily return| falls in range):
  days_bw_15_20perc : |ret| >= 0.15            (no upper cap, 20%+ included)
  days_bw_10_15perc : 0.10 <= |ret| < 0.15
  days_bw_5_10perc  : 0.05 <= |ret| < 0.10
  days_bw_2_5perc   : 0.02 <= |ret| < 0.05

Classification cascade (first match wins, top to bottom):
  days_bw_15_20perc > 2  -> EXTREME_LOTTERY
  days_bw_15_20perc > 0  -> LOTTERY
  days_bw_10_15perc > 0  -> BORDER_LOTTERY
  days_bw_5_10perc  > 0  -> CAUTIOUS
  days_bw_2_5perc   > 0  -> ALRIGHT
  else                   -> BORING

NOTE the asymmetric threshold: only EXTREME_LOTTERY requires >2 occurrences;
every other tier triggers on a single qualifying day. This is intentional —
confirmed explicitly, not a bug.
"""
import numpy as np
import pandas as pd


def compute(prices: pd.DataFrame, T, all_dates) -> pd.DataFrame:
    """
    prices   : full prices.parquet
    T        : robustly-resolved T
    all_dates: sorted list of trading dates <= T

    Returns DataFrame: symbol, days_bw_15_20perc, days_bw_10_15perc,
                        days_bw_5_10perc, days_bw_2_5perc, lottery_class
    """
    T_64 = all_dates[-65]  # anchor close, one day before the 63-day return window starts

    window = prices[(prices["date"] >= T_64) & (prices["date"] <= T)].copy()
    window = window.sort_values(["symbol", "date"])

    window["daily_ret"] = window.groupby("symbol")["close"].pct_change()

    # drop the anchor row itself (NaN daily_ret) -> leaves exactly 63 return obs per symbol
    rets = window.dropna(subset=["daily_ret"]).copy()
    rets["abs_ret"] = rets["daily_ret"].abs()

    def bucket_counts(g):
        return pd.Series(
            {
                "days_bw_15_20perc": (g["abs_ret"] >= 0.15).sum(),
                "days_bw_10_15perc": ((g["abs_ret"] >= 0.10) & (g["abs_ret"] < 0.15)).sum(),
                "days_bw_5_10perc": ((g["abs_ret"] >= 0.05) & (g["abs_ret"] < 0.10)).sum(),
                "days_bw_2_5perc": ((g["abs_ret"] >= 0.02) & (g["abs_ret"] < 0.05)).sum(),
            }
        )

    out = rets.groupby("symbol", group_keys=False).apply(bucket_counts, include_groups=False)
    out = out.reset_index()

    conditions = [
        out["days_bw_15_20perc"] > 2,
        out["days_bw_15_20perc"] > 0,
        out["days_bw_10_15perc"] > 0,
        out["days_bw_5_10perc"] > 0,
        out["days_bw_2_5perc"] > 0,
    ]
    choices = ["EXTREME_LOTTERY", "LOTTERY", "BORDER_LOTTERY", "CAUTIOUS", "ALRIGHT"]
    out["lottery_class"] = np.select(conditions, choices, default="BORING")

    return out[
        ["symbol", "days_bw_15_20perc", "days_bw_10_15perc", "days_bw_5_10perc", "days_bw_2_5perc", "lottery_class"]
    ]
