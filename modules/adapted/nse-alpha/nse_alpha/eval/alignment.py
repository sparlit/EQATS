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


"""Signal-to-return alignment — THE ONLY place forward-return alignment is performed.

Architecture
------------
Every signal in this pipeline is computed using only data available at date t
(close of business on day t).  To avoid lookahead bias, we enforce a full
one-day implementation gap before the signal is used.

Alignment diagram::

    ┌───────────────┬───────────────┬────────────────────────────┐
    │    Date t     │  Date t+1     │     Date t+1+h             │
    │   (signal     │  (impl gap:   │   (forward return          │
    │    computed)  │   not traded) │    realised here)          │
    └───────────────┴───────────────┴────────────────────────────┘
                    ←── IMPLEMENTATION_GAP ──→←── horizon h ────→

    signal(t) predicts  return(t+1 → t+1+h)

The implementation gap is a named constant.  It must NOT be hardcoded as an
inline integer anywhere else in the codebase.

Rules
-----
* This module is the ONLY place ``shift()`` or any temporal offset is applied
  to align signals to future returns.
* Signal modules NEVER call ``shift()``.
* Return computation is done here, not in signal modules.
* The ``horizon`` parameter controls how many days forward the return spans.
"""


import numpy as np
import pandas as pd

# Named constant — do not inline this integer anywhere else.
IMPLEMENTATION_GAP: int = 1


def align_signal_to_returns(
    signal: pd.Series,
    panel: pd.DataFrame,
    horizon: int = 1,
) -> pd.DataFrame:
    """Align *signal* at date t to the h-day forward return from t+gap to t+gap+h.

    Parameters
    ----------
    signal:
        Raw signal scores, indexed by ``(date, symbol)``.
    panel:
        Full tidy panel with ``adj_close`` column, indexed by ``(date, symbol)``.
    horizon:
        Number of trading days for the forward return (h in diagram above).

    Returns
    -------
    pd.DataFrame
        Columns ``signal`` and ``fwd_return``, indexed by ``(date, symbol)``.
        Date index is the *signal date* (t), not the return realisation date.
        Only rows where both signal and forward return are non-NaN are returned.

    Notes
    -----
    The forward return is the compounded log-return from close of t+gap to
    close of t+gap+h.  Using log-returns ensures additivity across horizons.

    adj_close is used exclusively for return computation.
    """
    # Step 1: Compute daily log-returns per symbol from adj_close
    adj = panel["adj_close"].unstack("symbol")  # date × symbol
    daily_log_ret = np.log(adj / adj.shift(1))  # daily log-return, NaN on first day

    # Step 2: Compute h-day forward log-return from t+gap onward
    # h-day return = sum of daily log returns from t+gap+1 to t+gap+h (inclusive)
    # rolling_sum[t] = r[t-h+1] + ... + r[t]
    # forward_ret[t] = rolling_sum shifted back: aligns to signal date t
    #   = r[t+gap+1] + r[t+gap+2] + ... + r[t+gap+h]
    rolling_sum = daily_log_ret.rolling(horizon).sum()  # rolling_sum[t] = r[t-h+1..t]
    # Shift back by (gap + horizon) to get forward return aligned to signal date
    total_shift = IMPLEMENTATION_GAP + horizon
    fwd_return = rolling_sum.shift(-total_shift)  # fwd_return[t] = rolling_sum[t+gap+h]

    fwd_return_series = fwd_return.stack(future_stack=True).rename("fwd_return")  # type: ignore[call-arg]

    # Step 3: Join signal with forward return
    aligned = pd.concat(
        [signal.rename("signal"), fwd_return_series],
        axis=1,
        join="inner",
    )
    aligned = aligned.dropna(subset=["signal", "fwd_return"])

    if aligned.empty:
        raise ValueError(
            "Alignment produced an empty DataFrame. "
            "Check that signal dates overlap with panel dates and "
            f"that there are at least {IMPLEMENTATION_GAP + horizon + 1} trading days."
        )

    return aligned


def compute_forward_returns(
    panel: pd.DataFrame,
    horizons: list[int],
) -> dict[int, pd.Series]:
    """Compute forward log-returns for multiple horizons from adj_close.

    Parameters
    ----------
    panel:
        Tidy panel with ``adj_close`` column.
    horizons:
        List of horizon lengths in trading days.

    Returns
    -------
    dict[int, pd.Series]
        Mapping from horizon to forward-return Series ``(date, symbol)``.
    """
    adj = panel["adj_close"].unstack("symbol")
    daily_log_ret = np.log(adj / adj.shift(1))

    result: dict[int, pd.Series] = {}
    for h in horizons:
        rolling_sum = daily_log_ret.rolling(h).sum()
        total_shift = IMPLEMENTATION_GAP + h
        fwd = rolling_sum.shift(-total_shift)
        result[h] = fwd.stack(future_stack=True).rename(f"fwd_return_{h}d")  # type: ignore[call-arg]
    return result
