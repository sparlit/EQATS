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
Stage 3 — Metric: Relative Strength

Measures each stock's cumulative log return over T-252 → T-21 relative to
(a) the equal-weighted market return and (b) its own industry's return,
over the same window.

alpha_12m1m_ew       : stock_cum_ret - market_cum_ret (equal-weighted all 500)
alpha_12m1m_industry : stock_cum_ret - industry_cum_ret (equal-weighted, same industry, self included)
momentum_rank_12m1m  : percentile rank of stock_cum_ret vs all 500 symbols (1.0 = top)

Inputs : window (prices T-252 → T-21 with log_ret computed), meta (universe_metadata)
Returns: dataframe with columns [symbol, alpha_12m1m_ew, alpha_12m1m_industry, momentum_rank_12m1m]
"""

import numpy as np
import pandas as pd


def compute(window: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    win = window.copy()
    win["log_ret"] = win.groupby("symbol")["close"].transform(lambda x: np.log(x / x.shift(1)))
    win = win.dropna(subset=["log_ret"])
    win["industry"] = win["symbol"].map(meta.set_index("symbol")["industry"])

    # Cumulative log return per symbol over window
    sym_cum_ret = win.groupby("symbol")["log_ret"].sum().rename("stock_cum_ret")

    # Equal-weighted market cumulative return
    market_cum_ret = win.groupby("date")["log_ret"].mean().sum()

    # Equal-weighted industry cumulative return (self included, same as leading_industry.py)
    industry_cum_ret = (
        win.groupby(["industry", "date"])["log_ret"]
        .mean()
        .groupby("industry")
        .sum()
        .rename("industry_cum_ret")
    )

    sym_industry = meta.set_index("symbol")["industry"]

    result = sym_cum_ret.reset_index()
    result["industry"] = result["symbol"].map(sym_industry)
    result["industry_cum_ret"] = result["industry"].map(industry_cum_ret)

    result["alpha_12m1m_ew"] = result["stock_cum_ret"] - market_cum_ret
    result["alpha_12m1m_industry"] = result["stock_cum_ret"] - result["industry_cum_ret"]
    result["momentum_rank_12m1m"] = result["stock_cum_ret"].rank(pct=True)

    return result[["symbol", "alpha_12m1m_ew", "alpha_12m1m_industry", "momentum_rank_12m1m"]]
