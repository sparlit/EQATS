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


"""Volatility signal family — 3 signals.

All volatility signals are negated (high vol → low expected return, i.e. low-vol
anomaly; Ang et al. 2006, Baker et al. 2011).

Signals
-------
idiosyncratic_vol : 60-day residual volatility from Nifty regression (negated)
realised_vol      : 60-day realised volatility of daily returns (negated)
vol_of_vol        : 60-day std of 21-day rolling volatility (negated)
"""


import numpy as np
import pandas as pd

from nse_alpha.signals.registry import register


@register(
    name="idiosyncratic_vol",
    family="Volatility",
    lookback_days=60,
    rationale=(
        "Idiosyncratic (market-beta-stripped) volatility is negatively priced "
        "in cross-section — low-idiosyncratic-vol stocks outperform high-vol stocks "
        "(Ang, Hodrick, Xing & Zhang 2006); negated so low vol → high signal."
    ),
)
def idiosyncratic_vol(panel: pd.DataFrame, **params: object) -> pd.Series:
    """60-day idiosyncratic volatility (residual from market regression), negated.

    Uses adj_close for daily log returns.
    Market proxy: equal-weighted cross-sectional average return.
    """
    adj = panel["adj_close"].unstack("symbol")
    log_ret = np.log(adj / adj.shift(1))
    mkt_ret = log_ret.mean(axis=1)

    window = 60
    result_dict: dict[str, pd.Series] = {}

    for sym in log_ret.columns:
        stock = log_ret[sym]
        idio = pd.Series(np.nan, index=adj.index)

        for i in range(window, len(adj)):
            y = stock.iloc[i - window : i].values
            x = mkt_ret.iloc[i - window : i].values
            valid = ~(np.isnan(x) | np.isnan(y))
            if valid.sum() < 20:
                continue
            beta = np.cov(y[valid], x[valid])[0, 1] / (np.var(x[valid]) + 1e-12)
            resids = y[valid] - beta * x[valid]
            idio.iloc[i] = float(np.std(resids, ddof=1))

        result_dict[sym] = idio

    result_df = pd.DataFrame(result_dict)
    signal = -result_df  # negate: low vol → high score
    return signal.stack(future_stack=True).rename("idiosyncratic_vol")  # type: ignore[call-arg]


@register(
    name="realised_vol",
    family="Volatility",
    lookback_days=60,
    rationale=(
        "60-day realised close-to-close volatility is negated to exploit the "
        "low-volatility anomaly: stocks with lower historical vol tend to "
        "outperform on a risk-adjusted basis (Baker, Bradley & Wurgler 2011)."
    ),
)
def realised_vol(panel: pd.DataFrame, **params: object) -> pd.Series:
    """60-day realised volatility (std of daily log-returns), negated.

    Uses adj_close for return computation.
    """
    adj = panel["adj_close"].unstack("symbol")
    log_ret = np.log(adj / adj.shift(1))
    vol60 = log_ret.rolling(60, min_periods=20).std(ddof=1)
    signal = -vol60  # negate: low vol → high score
    return signal.stack(future_stack=True).rename("realised_vol")  # type: ignore[call-arg]


@register(
    name="vol_of_vol",
    family="Volatility",
    lookback_days=81,  # 60d outer window + 21d inner window
    rationale=(
        "Volatility-of-volatility (VoV) captures regime uncertainty and is associated "
        "with lower expected returns; stocks with stable volatility regimes tend "
        "to outperform those with erratic vol (Huang et al. 2012); negated so low VoV "
        "→ high signal."
    ),
)
def vol_of_vol(panel: pd.DataFrame, **params: object) -> pd.Series:
    """60-day standard deviation of 21-day rolling realised vol, negated.

    Uses adj_close.
    """
    adj = panel["adj_close"].unstack("symbol")
    log_ret = np.log(adj / adj.shift(1))
    vol21 = log_ret.rolling(21, min_periods=10).std(ddof=1)
    vov60 = vol21.rolling(60, min_periods=20).std(ddof=1)
    signal = -vov60  # negate: low VoV → high score
    return signal.stack(future_stack=True).rename("vol_of_vol")  # type: ignore[call-arg]
