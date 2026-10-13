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


"""Decile portfolio construction and long-short spread statistics."""


import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
N_DECILES: int = 10


def compute_decile_portfolios(aligned: pd.DataFrame) -> pd.DataFrame:
    """Assign stocks to signal deciles and compute equal-weighted returns.

    Parameters
    ----------
    aligned:
        Columns ``signal``, ``fwd_return``.  MultiIndex ``(date, symbol)``.

    Returns
    -------
    pd.DataFrame
        Columns D1 (lowest signal) through D10 (highest signal), each
        containing the equal-weighted return of that decile for that date.
        Index: date.
    """

    def _decile_returns(g: pd.DataFrame) -> pd.Series:
        n = len(g.dropna())
        if n < 2:
            return pd.Series(dtype=float)
        if n >= N_DECILES:
            try:
                labels = pd.qcut(g["signal"], q=N_DECILES, labels=False, duplicates="drop")
                ew_ret = g["fwd_return"].groupby(labels).mean()
                # Rename to D1..D10
                ew_ret.index = [f"D{i + 1}" for i in ew_ret.index]
                return ew_ret
            except (ValueError, KeyError, TypeError):
                logger.debug("Failed 10-decile cut, falling back to 2-quantile cut")
        # Fallback for smaller universes: top vs bottom halves
        try:
            labels = pd.qcut(g["signal"], q=2, labels=False, duplicates="drop")
            ew_ret = g["fwd_return"].groupby(labels).mean()
            out: dict[str, float] = {}
            if 0 in ew_ret.index:
                out["D1"] = float(ew_ret[0])
            if 1 in ew_ret.index:
                out["D10"] = float(ew_ret[1])
            return pd.Series(out)
        except (ValueError, KeyError, TypeError):
            return pd.Series(dtype=float)

    result = aligned.groupby(level="date").apply(_decile_returns)
    return result


def compute_ls_spread(decile_returns: pd.DataFrame) -> pd.Series:
    """Compute long-short spread: D10 (top) minus D1 (bottom), half-sized legs.

    Returns
    -------
    pd.Series
        Daily long-short return series (indexed by date).
    """
    if "D10" not in decile_returns.columns or "D1" not in decile_returns.columns:
        raise ValueError("decile_returns must contain columns 'D1' and 'D10'")
    spread = 0.5 * decile_returns["D10"] - 0.5 * decile_returns["D1"]
    return spread.rename("ls_spread")


def compute_sharpe(
    returns: pd.Series,
    annualise: int = 252,
) -> float:
    """Annualised Sharpe ratio of a return series (assumes zero risk-free rate).

    Parameters
    ----------
    returns:
        Daily return series.
    annualise:
        Number of periods per year.  Default 252 trading days.

    Returns
    -------
    float
        Annualised Sharpe ratio.  Returns ``nan`` if std is 0 or series is empty.
    """
    clean = returns.dropna()
    if len(clean) < 2:
        return float("nan")
    mu = clean.mean()
    sigma = clean.std(ddof=1)
    if sigma == 0:
        return float("nan")
    return float((mu / sigma) * np.sqrt(annualise))


def compute_cumulative_returns(
    gross_spread: pd.Series,
    net_spread: pd.Series,
) -> pd.DataFrame:
    """Compute cumulative (compounded) return paths for gross and net spreads.

    Returns
    -------
    pd.DataFrame
        Columns ``gross`` and ``net``, index: date.
    """
    gross_cum = (1 + gross_spread).cumprod() - 1
    net_cum = (1 + net_spread).cumprod() - 1
    return pd.DataFrame({"gross": gross_cum, "net": net_cum})
