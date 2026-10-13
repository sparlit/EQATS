from __future__ import annotations

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


"""Momentum signal family — 4 signals.

All signals use ONLY data available at date t (data index <= t).
No shifting, no forward-return alignment is done here.
All temporal alignment is handled exclusively in eval/alignment.py.

Signals
-------
mom_12_1  : 12-1 month momentum (252-day minus last 21 days)
mom_6_1   : 6-1 month momentum (126-day minus last 21 days)
mom_21d   : 21-day short-term momentum
residual_mom : Cumulative residual from Nifty market regression over 252 days
"""


import logging

import numpy as np
import pandas as pd
from nse_alpha.signals.registry import register

logger = logging.getLogger(__name__)


@register(
    name="mom_12_1",
    family="Momentum",
    lookback_days=252,
    rationale=(
        "12-1 month momentum captures the medium-term price continuation effect "
        "documented by Jegadeesh & Titman (1993); the skip-month avoids reversal "
        "contamination from the most-recent month."
    ),
)
def mom_12_1(panel: pd.DataFrame, **params: object) -> pd.Series:
    """12-1 month momentum: cumulative log-return from t-252 to t-21.

    Uses adj_close for return computation.
    At date t, looks back 252 days and skips the most recent 21 days.
    """
    adj = panel["adj_close"].unstack("symbol")  # date × symbol
    # Cumulative 252-day log return, skipping last 21 days
    # = log(adj[t-21] / adj[t-252])
    # Implemented as sum of daily log returns from t-252+1 to t-21
    mom = np.log(adj.shift(21) / adj.shift(252))
    return mom.stack(future_stack=True).rename("mom_12_1")  # type: ignore[call-arg]


@register(
    name="mom_6_1",
    family="Momentum",
    lookback_days=126,
    rationale=(
        "6-1 month momentum is a shorter lookback variant that captures more recent "
        "price trends while still skipping the reversal-prone last month."
    ),
)
def mom_6_1(panel: pd.DataFrame, **params: object) -> pd.Series:
    """6-1 month momentum: cumulative log-return from t-126 to t-21."""
    adj = panel["adj_close"].unstack("symbol")
    mom = np.log(adj.shift(21) / adj.shift(126))
    return mom.stack(future_stack=True).rename("mom_6_1")  # type: ignore[call-arg]


@register(
    name="mom_21d",
    family="Momentum",
    lookback_days=21,
    rationale=(
        "21-day short-term momentum captures recent price trends without the skip-month "
        "filter; useful as a complement to longer-horizon signals and tests "
        "short-term continuation vs reversal dynamics."
    ),
)
def mom_21d(panel: pd.DataFrame, **params: object) -> pd.Series:
    """21-day short-term momentum: cumulative log-return over last 21 days."""
    adj = panel["adj_close"].unstack("symbol")
    mom = np.log(adj / adj.shift(21))
    return mom.stack(future_stack=True).rename("mom_21d")  # type: ignore[call-arg]


@register(
    name="residual_mom",
    family="Momentum",
    lookback_days=252,
    rationale=(
        "Residual momentum isolates the stock-specific component of past returns "
        "by removing market (Nifty) co-movement, targeting the idiosyncratic "
        "continuation effect described by Blitz et al. (2011)."
    ),
)
def residual_mom(panel: pd.DataFrame, **params: object) -> pd.Series:
    """Residual momentum: cumulative idiosyncratic return after removing Nifty beta.

    Methodology:
        1. Compute excess log-returns for each stock and for Nifty over a 252-day window.
        2. Regress each stock's excess returns on Nifty excess returns (OLS).
        3. Cumulate the OLS residuals (the idiosyncratic, market-adjusted return).

    Nifty proxy: cross-sectional equal-weighted average return of universe
    (used when ^NSEI is not in the panel).
    """
    adj = panel["adj_close"].unstack("symbol")  # date × symbol
    log_ret = np.log(adj / adj.shift(1))

    # Market proxy: equal-weighted return of all universe stocks
    mkt_ret = log_ret.mean(axis=1)  # date-level Series

    window = 252
    result_dict: dict[str, pd.Series] = {}

    for sym in log_ret.columns:
        stock_ret = log_ret[sym].dropna()
        dates_available = stock_ret.index

        cumulative_resid = pd.Series(np.nan, index=adj.index)

        for t_idx in range(window, len(dates_available)):
            window_dates = dates_available[t_idx - window : t_idx]
            y = stock_ret[window_dates].values
            x = mkt_ret[window_dates].values
            # Remove dates where market return is NaN
            valid = ~(np.isnan(x) | np.isnan(y))
            if valid.sum() < 60:
                continue
            beta = np.cov(y[valid], x[valid])[0, 1] / (np.var(x[valid]) + 1e-12)
            resids = y[valid] - beta * x[valid]
            cumulative_resid.at[dates_available[t_idx]] = float(resids.sum())

        result_dict[sym] = cumulative_resid

    result_df = pd.DataFrame(result_dict)
    return result_df.stack(future_stack=True).rename("residual_mom")  # type: ignore[call-arg]
