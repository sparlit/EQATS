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
Stage 3 — Metric: Leading Industry

For each stock, scores its industry's cumulative log return over T-252 → T-21
relative to all other industries.

Inputs : window (prices T-252 → T-21 with log_ret computed), meta (universe_metadata)
Returns: dataframe with columns [symbol, industry_cum_ret, industry_rank]

industry_cum_ret : sum of daily equal-weighted industry log returns over window
industry_rank    : percentile rank of industry_cum_ret across all industries (1.0 = top)
"""

import numpy as np
import pandas as pd


def compute(window: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    win = window.copy()
    win["log_ret"] = win.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
    win = win.dropna(subset=["log_ret"])
    win["industry"] = win["symbol"].map(meta.set_index("symbol")["industry"])

    # Equal-weighted industry return per day, summed over window
    ind_cum_ret = (
        win.groupby(["industry", "date"])["log_ret"]
        .mean()
        .groupby("industry")
        .sum()
        .rename("industry_cum_ret")
    )

    # Percentile rank across industries
    ind_rank = ind_cum_ret.rank(pct=True).rename("industry_rank")

    # Map back to symbols
    sym_industry = meta.set_index("symbol")["industry"]
    result = meta[["symbol"]].copy()
    result["industry_cum_ret"] = result["symbol"].map(sym_industry).map(ind_cum_ret)
    result["industry_rank"] = result["symbol"].map(sym_industry).map(ind_rank)

    return result[["symbol", "industry_cum_ret", "industry_rank"]]
