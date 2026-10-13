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


"""Range signal family — 1 signal.

Signals
-------
parkinson_vs_cc : Parkinson high-low vol relative to close-to-close vol (21d), negated
"""


import numpy as np
import pandas as pd
from nse_alpha.signals.registry import register


@register(
    name="parkinson_vs_cc",
    family="Range",
    lookback_days=21,
    rationale=(
        "The Parkinson (1980) high-low volatility estimator is more efficient "
        "than close-to-close vol when intraday range is informative.  The ratio "
        "Parkinson/CC-vol captures the degree of intraday gapping: high ratios "
        "may signal information events or manipulation; we negate it to align "
        "with the low-volatility premium."
    ),
)
def parkinson_vs_cc(panel: pd.DataFrame, **params: object) -> pd.Series:
    """21-day Parkinson vol / 21-day close-to-close vol, negated.

    Parkinson estimator: sigma_P^2 = (1 / (4 * n * ln2)) * sum(ln(H_t/L_t)^2)
    CC vol: std(daily log-returns over 21 days)

    Uses raw high and low prices for Parkinson estimator.
    Uses adj_close for close-to-close return computation.

    The ratio is negated because high intraday vol relative to close-to-close
    vol is associated with lower expected returns (consistent with the vol anomaly).
    """
    high = panel["high"].unstack("symbol")  # raw high — actual intraday high
    low = panel["low"].unstack("symbol")  # raw low — actual intraday low
    adj = panel["adj_close"].unstack("symbol")

    # Parkinson variance estimator (rolling 21d)
    ln_hl_sq = np.log(high / low) ** 2
    parkinson_var = ln_hl_sq.rolling(21, min_periods=10).mean() / (4 * np.log(2))
    parkinson_sigma = np.sqrt(parkinson_var)

    # Close-to-close vol (rolling 21d)
    log_ret = np.log(adj / adj.shift(1))
    cc_sigma = log_ret.rolling(21, min_periods=10).std(ddof=1)

    # Ratio: Parkinson / CC, clipped to avoid extreme outliers
    ratio = parkinson_sigma / (cc_sigma + 1e-8)
    signal = -ratio  # negate: low ratio → high score
    return signal.stack(future_stack=True).rename("parkinson_vs_cc")  # type: ignore[call-arg]
