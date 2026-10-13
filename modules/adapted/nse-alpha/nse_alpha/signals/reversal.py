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


"""Reversal signal family — 3 signals.

All signals are negated returns (high past return → low expected future return).
No shifting or forward-return alignment here — that is in eval/alignment.py.

Signals
-------
rev_5d              : 5-day reversal (negative of 5-day cumulative return)
rev_1d              : 1-day reversal (negative of yesterday's return)
overnight_vs_intraday : Overnight return minus intraday return
"""


import numpy as np
import pandas as pd
from nse_alpha.signals.registry import register


@register(
    name="rev_5d",
    family="Reversal",
    lookback_days=5,
    rationale=(
        "5-day short-term reversal exploits the liquidity-driven mean-reversion "
        "effect in individual stock returns; stocks that have fallen sharply "
        "over the past week tend to recover (Lehmann 1990, Jegadeesh 1990)."
    ),
)
def rev_5d(panel: pd.DataFrame, **params: object) -> pd.Series:
    """5-day reversal: negative of 5-day cumulative log-return.

    Uses adj_close.  Signal is negative so that high past return → low score.
    """
    adj = panel["adj_close"].unstack("symbol")
    log_ret_5d = np.log(adj / adj.shift(5))
    signal = -log_ret_5d  # negate: reversal hypothesis
    return signal.stack(future_stack=True).rename("rev_5d")  # type: ignore[call-arg]


@register(
    name="rev_1d",
    family="Reversal",
    lookback_days=1,
    rationale=(
        "1-day overnight reversal captures intraday bid-ask bounce and short-term "
        "microstructure mean-reversion; stocks that fall sharply in one day tend "
        "to recover the next (Lehmann 1990)."
    ),
)
def rev_1d(panel: pd.DataFrame, **params: object) -> pd.Series:
    """1-day reversal: negative of yesterday's daily log-return.

    Uses adj_close.
    """
    adj = panel["adj_close"].unstack("symbol")
    log_ret_1d = np.log(adj / adj.shift(1))
    signal = -log_ret_1d  # negate for reversal
    return signal.stack(future_stack=True).rename("rev_1d")  # type: ignore[call-arg]


@register(
    name="overnight_vs_intraday",
    family="Reversal",
    lookback_days=20,
    rationale=(
        "The overnight-minus-intraday return split isolates informed trading "
        "(overnight, where institutions act on information) from noise trading "
        "(intraday); high overnight relative to intraday may signal positive "
        "information flow (Lou, Polk & Skouras 2019)."
    ),
)
def overnight_vs_intraday(panel: pd.DataFrame, **params: object) -> pd.Series:
    """Overnight return fraction: rolling 20-day ratio of overnight to intraday.

    Overnight return at t = log(open_t / adj_close_{t-1})
    Intraday return at t = log(adj_close_t / open_t)
    Signal = 20d mean(overnight) - 20d mean(intraday)

    Uses raw open and adj_close.
    """
    adj = panel["adj_close"].unstack("symbol")
    opn = panel["open"].unstack("symbol")  # raw open — actual open price on day t

    # Overnight: from previous close to today's open
    overnight = np.log(opn / adj.shift(1))  # type: ignore[operator]
    # Intraday: from today's open to today's close (use adj_close for close)
    intraday = np.log(adj / opn)  # type: ignore[operator]

    # Rolling 20-day mean difference
    signal = overnight.rolling(20).mean() - intraday.rolling(20).mean()
    return signal.stack(future_stack=True).rename("overnight_vs_intraday")  # type: ignore[call-arg]
