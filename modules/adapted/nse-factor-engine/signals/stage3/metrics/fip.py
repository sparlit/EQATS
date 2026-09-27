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
Stage 3 — Metric: FIP Score, % Positive Days, % Negative Days

Inputs : window (prices T-252 → T-21), signals (stage2, for ret_12m1m)
Returns: dataframe with columns [symbol, fip_score, pct_pos_days, pct_neg_days]
"""

import numpy as np
import pandas as pd


def compute(window: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    log_rets = window.copy()
    log_rets["log_ret"] = log_rets.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
    log_rets = log_rets.dropna(subset=["log_ret"])

    def fip_components(group):
        total = len(group)
        if total == 0:
            return pd.Series({"pct_pos_days": np.nan, "pct_neg_days": np.nan})
        pos = (group["log_ret"] > 0).sum()
        neg = (group["log_ret"] < 0).sum()
        return pd.Series(
            {
                "pct_pos_days": pos / total,
                "pct_neg_days": neg / total,
            }
        )

    fip_df = log_rets.groupby("symbol", group_keys=False).apply(fip_components, include_groups=False).reset_index()

    fip_df = fip_df.merge(signals[["symbol", "ret_12m1m"]], on="symbol", how="left")
    fip_df["fip_score"] = np.sign(fip_df["ret_12m1m"]) * (fip_df["pct_neg_days"] - fip_df["pct_pos_days"])
    return fip_df[["symbol", "fip_score", "pct_pos_days", "pct_neg_days"]]
