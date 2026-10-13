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


"""Liquidity signal family — 3 signals.

Signals
-------
amihud_illiquidity  : 60-day Amihud illiquidity ratio (negated → more liquid = better)
turnover_ratio      : 20-day median turnover_value vs its 252-day median (z-scored)
volume_shock        : 20-day volume z-score vs 252-day rolling mean

Note on sign conventions
------------------------
Amihud illiquidity: HIGH illiquidity → LOW expected return in many studies
(illiquid stocks are riskier and demand a premium in theory; however in
practice illiquid stocks often *underperform* after controlling for size).
We negate so that the signal = "liquidity preference" (more liquid → higher score).

turnover_ratio and volume_shock: positive spikes in volume are associated with
attention effects and short-term reversal (Gervais et al. 2001).  We report
the raw z-score and let the IC sign determine the direction.
"""


import numpy as np
import pandas as pd

from nse_alpha.signals.registry import register


@register(
    name="amihud_illiquidity",
    family="Liquidity",
    lookback_days=60,
    rationale=(
        "Amihud (2002) illiquidity ratio (|return| / volume) measures price impact "
        "per unit of volume; we negate it so that high liquidity → high signal, "
        "consistent with the empirical finding that liquidity is priced."
    ),
)
def amihud_illiquidity(panel: pd.DataFrame, **params: object) -> pd.Series:
    """60-day mean Amihud illiquidity ratio, negated.

    Amihud ratio at date t = |ret_t| / turnover_value_t
    Uses raw close for volume computation (turnover_value = close * volume).
    Uses adj_close for return computation.
    """
    adj = panel["adj_close"].unstack("symbol")
    log_ret = np.log(adj / adj.shift(1)).abs()  # |daily log-return|
    tv = panel["turnover_value"].unstack("symbol")  # raw close * volume (Rs)

    # Avoid division by zero
    tv_safe = tv.replace(0, np.nan)
    amihud_daily = log_ret / tv_safe * 1e7  # scale to reasonable numeric range

    amihud60 = amihud_daily.rolling(60, min_periods=20).mean()
    signal = -amihud60  # negate: more liquid (low Amihud) → high score
    return signal.stack(future_stack=True).rename("amihud_illiquidity")  # type: ignore[call-arg]


@register(
    name="turnover_ratio",
    family="Liquidity",
    lookback_days=252,
    rationale=(
        "A stock's 20-day trading activity relative to its own 252-day median "
        "identifies periods of unusual investor attention; abnormal turnover is "
        "associated with subsequent price reversals (Gervais, Kaniel & Mingelgrin 2001)."
    ),
)
def turnover_ratio(panel: pd.DataFrame, **params: object) -> pd.Series:
    """Ratio of 20-day median turnover_value to 252-day median, z-scored.

    Uses raw turnover_value (volume * raw close) — captures actual traded Rs value.
    """
    tv = panel["turnover_value"].unstack("symbol")

    adv20 = tv.rolling(20, min_periods=10).median()
    adv252 = tv.rolling(252, min_periods=100).median()

    ratio = np.log(adv20 / adv252.replace(0, np.nan))  # log-ratio for stationarity
    return ratio.stack(future_stack=True).rename("turnover_ratio")  # type: ignore[call-arg]


@register(
    name="volume_shock",
    family="Liquidity",
    lookback_days=252,
    rationale=(
        "A sudden spike in trading volume relative to the trailing 252-day mean "
        "indicates unusual attention and is associated with short-term continuation "
        "followed by reversal; the z-score normalises for differences in base volume "
        "across stocks (Gervais et al. 2001)."
    ),
)
def volume_shock(panel: pd.DataFrame, **params: object) -> pd.Series:
    """20-day average volume vs 252-day rolling mean, in z-score terms.

    Uses raw volume (shares).
    """
    vol = panel["volume"].unstack("symbol")

    vol20 = vol.rolling(20, min_periods=10).mean()
    vol252_mean = vol.rolling(252, min_periods=100).mean()
    vol252_std = vol.rolling(252, min_periods=100).std(ddof=1)

    z_score = (vol20 - vol252_mean) / (vol252_std + 1e-8)
    return z_score.stack(future_stack=True).rename("volume_shock")  # type: ignore[call-arg]
