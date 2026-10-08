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


from typing import Any

import numpy as np
from numba import float64, from_dtype, int64
from numba.experimental import jitclass

from .types import state_values_dtype


class StateValues:
    arr: from_dtype(state_values_dtype)[:]

    def __init__(self, arr: np.ndarray[Any, state_values_dtype]):
        self.arr = arr

    @property
    def position(self) -> float64:
        """
        Returns the open position.
        """
        return self.arr[0].position

    @property
    def balance(self) -> float64:
        """
        Returns the cash balance.
        """
        return self.arr[0].balance

    @property
    def fee(self) -> float64:
        """
        Returns the accumulated fee.
        """
        return self.arr[0].fee

    @property
    def num_trades(self) -> int64:
        """
        Returns the total number of trades.
        """
        return self.arr[0].num_trades

    @property
    def trading_volume(self) -> float64:
        """
        Returns the total trading volume.
        """
        return self.arr[0].trading_volume

    @property
    def trading_value(self) -> float64:
        """
        Returns the total trading value.
        """
        return self.arr[0].trading_value


StateValues_ = jitclass(StateValues)
