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


"""
Rebalancing policy: which sessions a portfolio resets its weights on.

Kept separate from the engine because the policy is the interesting variable —
it is what turns one allocation into a family of strategies, and it is where
the reference products stop (calendar only). Drift bands are here too, since
"rebalance when it has actually drifted" is both cheaper and closer to what an
investor really does than "rebalance because it is April".
"""


from dataclasses import dataclass

import numpy as np
import pandas as pd

# Calendar policies, as pandas period aliases. `never` is buy and hold.
CALENDAR_RULES = {
    "never": None,
    "monthly": "ME",
    "quarterly": "QE",
    "yearly": "YE",
}


@dataclass(frozen=True)
class RebalancePolicy:
    """
    How and when to reset weights back to target.

    ``rule`` is one of ``CALENDAR_RULES``. ``drift_band`` optionally adds an
    event trigger: when any holding's weight has moved more than this many
    percentage points (absolute) from its target, rebalance on that session
    regardless of the calendar. ``0`` disables it.
    """

    rule: str = "never"
    drift_band: float = 0.0

    def __post_init__(self) -> None:
        if self.rule not in CALENDAR_RULES:
            raise ValueError(
                f"unknown rebalance rule {self.rule!r}; expected one of {sorted(CALENDAR_RULES)}"
            )
        if not 0.0 <= self.drift_band < 1.0:
            raise ValueError(
                f"drift_band is a fraction of 1.0 (0.05 = 5 percentage points), "
                f"got {self.drift_band}"
            )

    @property
    def is_buy_and_hold(self) -> bool:
        return CALENDAR_RULES[self.rule] is None and self.drift_band == 0.0


def calendar_dates(index: pd.DatetimeIndex, rule: str) -> pd.DatetimeIndex:
    """
    The last available session of each period in ``index``.

    Resolved against the sessions that actually exist rather than against
    month-ends: 31 March may be a holiday, and rebalancing on a date the market
    was shut is not a thing that can happen.
    """
    alias = CALENDAR_RULES[rule]
    if alias is None or len(index) == 0:
        return pd.DatetimeIndex([])
    marks = pd.Series(index, index=index).groupby(index.to_period(alias[0])).last()
    # The first session is when the portfolio is bought, not a rebalance.
    return pd.DatetimeIndex(marks.values).difference(index[:1])


def drifted(weights: np.ndarray, target: np.ndarray, band: float) -> bool:
    """
    Whether any holding has drifted more than ``band`` from its target weight.

    Absolute percentage points, not relative: a 2% holding doubling to 4% is a
    2-point move, which matters far less to a portfolio than a 40% holding
    moving to 42% would suggest under a relative test.
    """
    if band <= 0.0:
        return False
    return bool(np.max(np.abs(weights - target)) > band)
