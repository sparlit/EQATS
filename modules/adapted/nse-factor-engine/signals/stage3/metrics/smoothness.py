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
Stage 3 — Metric: Momentum Smoothness

Inputs : window (prices T-252 → T-21)
Returns: dataframe with columns [symbol, smoothness]
"""

import numpy as np
import pandas as pd


def compute(window: pd.DataFrame) -> pd.DataFrame:
    def compute_smoothness(group):
        group = group.reset_index(drop=True)
        n = len(group)
        complete_weeks = n // 5
        if complete_weeks == 0:
            return pd.Series({"smoothness": np.nan})
        pos_weeks = 0
        for i in range(complete_weeks):
            start = i * 5
            end = start + 4
            if group.loc[end, "close"] > group.loc[start, "open"]:
                pos_weeks += 1
        return pd.Series({"smoothness": pos_weeks / complete_weeks})

    return (
        window.groupby("symbol", group_keys=False)
        .apply(compute_smoothness, include_groups=False)
        .reset_index()
    )
