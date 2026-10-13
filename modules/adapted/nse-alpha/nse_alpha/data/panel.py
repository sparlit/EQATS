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


"""Panel builder — assembles the core tidy MultiIndex panel.

The panel is the single data contract for the entire pipeline::

    MultiIndex: (date, symbol)
    Columns:
        open            float64   raw open price
        high            float64   raw high price
        low             float64   raw low price
        close           float64   raw close price
        adj_close       float64   split-and-dividend-adjusted close
        volume          float64   traded volume (shares)
        turnover_value  float64   volume * raw_close (Rs, approximate traded value)

Usage of adj_close vs close
----------------------------
* ``adj_close`` MUST be used for all return computation (signal inputs, IC
  calculation, portfolio returns).  This ensures splits and dividends are
  accounted for.
* ``close`` and ``volume`` are used for ``turnover_value`` and for the
  Amihud illiquidity signal, because they represent the *actual* traded price
  and volume on the day.  Using adj_close here would distort historical ADV.
"""


import logging

import pandas as pd
from nse_alpha.data.cache import load_panel
from nse_alpha.data.ingest import download_universe

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume", "turnover_value"]


def build_panel(
    symbols: list[str],
    start: str,
    end: str,
    *,
    download: bool = True,
    force: bool = False,
) -> pd.DataFrame:
    """Build the tidy panel for *symbols* over [start, end].

    Parameters
    ----------
    symbols:
        List of tickers with ``.NS`` suffix.
    start:
        ISO-8601 start date (inclusive).
    end:
        ISO-8601 end date (inclusive).
    download:
        If ``True`` (default), fetch missing data from yfinance.
        Set to ``False`` in tests to avoid network calls.
    force:
        If ``True``, re-download data from yfinance even if cached.

    Returns
    -------
    pd.DataFrame
        MultiIndex ``(date, symbol)``, columns as per the module docstring.
    """
    if download:
        download_universe(symbols, start, end, force=force)

    panel = load_panel(symbols, start, end)

    if panel.empty:
        logger.warning("Panel is empty for symbols=%s, start=%s, end=%s", symbols, start, end)
        return panel

    _validate_panel(panel)
    return panel


def validate_panel(panel: pd.DataFrame) -> None:
    """Public validator — raises ``ValueError`` on any schema violation."""
    _validate_panel(panel)


def _validate_panel(panel: pd.DataFrame) -> None:
    """Internal schema check."""
    if not isinstance(panel.index, pd.MultiIndex):
        raise ValueError("Panel must have a MultiIndex")
    if list(panel.index.names) != ["date", "symbol"]:
        raise ValueError(f"Panel index names must be ['date', 'symbol'], got {panel.index.names}")
    missing = [c for c in REQUIRED_COLUMNS if c not in panel.columns]
    if missing:
        raise ValueError(f"Panel missing required columns: {missing}")
    if panel.index.duplicated().any():
        raise ValueError("Panel contains duplicate (date, symbol) pairs")


def compute_returns(panel: pd.DataFrame) -> pd.Series:
    """Compute daily log-returns from adj_close.

    Uses adj_close (split-and-dividend-adjusted) for all return computation.
    Returns are computed per-symbol, one-period (daily).

    Returns
    -------
    pd.Series
        MultiIndex ``(date, symbol)`` with daily log-returns.
        The first date for each symbol will be NaN.
    """
    import numpy as np

    adj = panel["adj_close"].unstack("symbol")  # date × symbol
    log_rets = np.log(adj / adj.shift(1))
    df = pd.DataFrame(log_rets)
    s = pd.Series(df.stack(future_stack=True))
    s.name = "return"
    return s
