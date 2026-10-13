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


"""Turnover calculation for long-short portfolios."""


import numpy as np
import pandas as pd


def compute_weights_from_deciles(
    aligned: pd.DataFrame,
    n_deciles: int = 10,
) -> pd.DataFrame:
    """Compute equal-weighted portfolio weights for the long-short strategy.

    Long leg: top decile (D10), weight = +1/n_long per stock.
    Short leg: bottom decile (D1), weight = -1/n_short per stock.
    Total portfolio is zero-cost (long + short = 0).

    Parameters
    ----------
    aligned:
        Columns ``signal``, ``fwd_return``.  MultiIndex ``(date, symbol)``.
    n_deciles:
        Number of signal deciles.

    Returns
    -------
    pd.DataFrame
        Weights for each (date, symbol) — columns: weight.
        Indexed by (date, symbol).
    """

    def _day_weights(g: pd.DataFrame) -> pd.Series:
        n = len(g.dropna())
        if n < 2:
            return pd.Series(0.0, index=g.index)
        if n >= n_deciles:
            try:
                labels = pd.qcut(g["signal"], q=n_deciles, labels=False, duplicates="drop")
                top = labels == (n_deciles - 1)
                bot = labels == 0
            except Exception:
                labels = pd.qcut(g["signal"], q=2, labels=False, duplicates="drop")
                top = labels == 1
                bot = labels == 0
        else:
            try:
                labels = pd.qcut(g["signal"], q=2, labels=False, duplicates="drop")
                top = labels == 1
                bot = labels == 0
            except Exception:
                return pd.Series(0.0, index=g.index)

        weights = pd.Series(0.0, index=g.index)
        n_top = int(top.sum())
        n_bot = int(bot.sum())
        if n_top > 0:
            weights[top] = 1.0 / n_top
        if n_bot > 0:
            weights[bot] = -1.0 / n_bot
        return weights

    result = aligned.groupby(level="date", group_keys=False).apply(_day_weights)
    if isinstance(result, pd.DataFrame):
        if "weight" in result.columns:
            df_out = result[["weight"]].copy()
        elif len(result.columns) == 1:
            df_out = result.copy()
            df_out.columns = ["weight"]
        else:
            s = result.stack()
            s.name = "weight"
            df_out = s.to_frame()
    else:
        s_out = pd.Series(result)
        s_out.name = "weight"
        df_out = s_out.to_frame()

    if isinstance(df_out.index, pd.MultiIndex) and list(df_out.index.names) != ["date", "symbol"]:
        df_out.index.names = ["date", "symbol"]
    return df_out


def compute_turnover(weights: pd.DataFrame) -> float:
    """Compute mean one-way turnover of the long-short portfolio.

    Turnover per period = sum(|w_t - w_{t-1}|) / 2
    Average over all dates.

    Parameters
    ----------
    weights:
        DataFrame with column ``weight`` and MultiIndex ``(date, symbol)``.

    Returns
    -------
    float
        Mean one-way turnover per rebalance (fraction of portfolio).
    """
    if weights.empty or "weight" not in weights.columns:
        return 0.0
    try:
        if isinstance(weights.index, pd.MultiIndex):
            if "symbol" in weights.index.names:
                w = weights["weight"].unstack("symbol").fillna(0.0)
            elif weights.index.nlevels >= 2:
                w = weights["weight"].unstack(1).fillna(0.0)
            else:
                return 0.0
        else:
            return 0.0
        delta = w.diff().abs().sum(axis=1) / 2.0
        val = float(delta.mean())
        return 0.0 if np.isnan(val) else val
    except Exception:
        return 0.0
