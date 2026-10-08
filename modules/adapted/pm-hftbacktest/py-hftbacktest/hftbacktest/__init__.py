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


from typing import Any, List

import numpy as np
from numba import njit
from numpy.typing import NDArray

from ._hftbacktest import BacktestAsset as BacktestAsset_
from ._hftbacktest import LiveInstrument, build_hashmap_backtest, build_roivec_backtest
from .binding import HashMapMarketDepthBacktest as HashMapMarketDepthBacktest_TypeHint
from .binding import HashMapMarketDepthBacktest_, ROIVectorMarketDepthBacktest_, event_dtype
from .binding import ROIVectorMarketDepthBacktest as ROIVectorMarketDepthBacktest_TypeHint
from .data.utils.polymarket import polymarket_to_hbt
from .order import (
    BUY,
    CANCELED,
    EXPIRED,
    FILLED,
    GTC,
    GTX,
    LIMIT,
    MARKET,
    NEW,
    NONE,
    SELL,
)
from .recorder import Recorder
from .types import (
    ADD_ORDER_EVENT,
    ALL_ASSETS,
    BUY_EVENT,
    CANCEL_ORDER_EVENT,
    DEPTH_BBO_EVENT,
    DEPTH_CLEAR_EVENT,
    DEPTH_EVENT,
    DEPTH_SNAPSHOT_EVENT,
    EVENT_ARRAY,
    EXCH_EVENT,
    FILL_EVENT,
    LOCAL_EVENT,
    MODIFY_ORDER_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
)

try:
    from ._hftbacktest import build_hashmap_livebot, build_roivec_livebot
    from .binding import (
        HashMapMarketDepthLiveBot as HashMapMarketDepthLiveBot_TypeHint,
    )
    from .binding import (
        HashMapMarketDepthLiveBot_,
        ROIVectorMarketDepthLiveBot_,
    )
    from .binding import (
        ROIVectorMarketDepthLiveBot as ROIVectorMarketDepthLiveBot_TypeHint,
    )

    LIVE_FEATURE = True
except:
    LIVE_FEATURE = False

__all__ = (
    "BacktestAsset",
    "BacktestAssetPoly",
    "init_orderbook",
    "HashMapMarketDepthBacktest",
    "ROIVectorMarketDepthBacktest",
    "LiveInstrument",
    "HashMapMarketDepthLiveBot",
    "ROIVectorMarketDepthLiveBot",
    "ALL_ASSETS",
    # Event flags
    "DEPTH_EVENT",
    "TRADE_EVENT",
    "DEPTH_CLEAR_EVENT",
    "DEPTH_SNAPSHOT_EVENT",
    "DEPTH_BBO_EVENT",
    "ADD_ORDER_EVENT",
    "CANCEL_ORDER_EVENT",
    "MODIFY_ORDER_EVENT",
    "FILL_EVENT",
    "EXCH_EVENT",
    "LOCAL_EVENT",
    "EXCH_EVENT",
    "LOCAL_EVENT",
    "BUY_EVENT",
    "SELL_EVENT",
    # Side
    "BUY",
    "SELL",
    # Order status
    "NONE",
    "NEW",
    "EXPIRED",
    "FILLED",
    "CANCELED",
    # Time-In-Force
    "GTC",
    "GTX",
    "LIMIT",
    "MARKET",
    "polymarket_to_hbt",
    "Recorder",
)

__version__ = "1.0.9"


class BacktestAsset(BacktestAsset_):
    def add_data(self, data: EVENT_ARRAY):
        self._add_data_ndarray(data.ctypes.data, len(data))
        return self

    def data(self, data: str | list[str] | EVENT_ARRAY | list[EVENT_ARRAY]):
        """
        Sets the feed data.

        Args:
            data: A list of file paths for the feed data in `.npz` format, or a list of NumPy arrays containing the feed
                  data.
        """
        if isinstance(data, str):
            self.add_file(data)
        elif isinstance(data, np.ndarray):
            self.add_data(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    self.add_file(item)
                elif isinstance(item, np.ndarray):
                    self.add_data(item)
                else:
                    raise ValueError
        else:
            raise ValueError
        return self

    def intp_order_latency(self, data: str | NDArray | list[str], latency_offset: int = 0):
        """
        Uses `IntpOrderLatency <https://docs.rs/hftbacktest/latest/hftbacktest/backtest/models/struct.IntpOrderLatency.html>`_
        for the order latency model.
        Please see the data format.
        The units of the historical latencies should match the timestamp units of your data.
        Nanoseconds are typically used in HftBacktest.

        Args:
            data: A list of file paths for the historical order latency data in `npz`, or a NumPy array of the
                  historical order latency data.
            latency_offset: the latency offset to adjust the order entry and response latency by the
                            specified amount. This is particularly useful in cross-exchange
                            backtesting, where the feed data is collected from a different site than
                            the one where the strategy is intended to run.
        """
        if isinstance(data, str):
            super().intp_order_latency([data], latency_offset)
        elif isinstance(data, np.ndarray):
            self._intp_order_latency_ndarray(data.ctypes.data, len(data), latency_offset)
        elif isinstance(data, list):
            super().intp_order_latency(data, latency_offset)
        else:
            raise ValueError
        return self

    def initial_snapshot(self, data: str | np.ndarray[Any, event_dtype]):
        """
        Sets the initial snapshot.

        Args:
            data: The initial snapshot file path, or a NumPy array of the initial snapshot.
        """
        if isinstance(data, str):
            super().initial_snapshot(data)
        elif isinstance(data, np.ndarray):
            self._initial_snapshot_ndarray(data.ctypes.data, len(data))
        else:
            raise ValueError
        return self


class BacktestAssetPoly(BacktestAsset):
    """
    BacktestAsset preset for Polymarket data.

    The Polymarket-specific fixed settings are applied at construction time.
    Data, latency, and fee model remain configurable through the normal
    BacktestAsset chain methods.
    """

    def __init__(self):
        super().__init__()
        self.linear_asset(1.0)
        self.risk_adverse_queue_model()
        self.tick_size(0.001)
        self.lot_size(0.001)
        self.last_trades_capacity(0)
        self.roi_lb(0.0)
        self.roi_ub(1.0)


@njit
def init_orderbook(hbt, asset_no=0, max_iter=10000):
    """Waits until the order book is initialized."""
    for _ in range(max_iter):
        if hbt.elapse(1_000_000) != 0:
            return False
        depth = hbt.depth(asset_no)
        if depth.best_bid_tick > 0 and depth.best_ask_tick > 0:
            return True
    return False


def HashMapMarketDepthBacktest(assets: list[BacktestAsset]) -> HashMapMarketDepthBacktest_TypeHint:
    """
    Constructs an instance of `HashMapMarketDepthBacktest`.

    Args:
        assets: A list of backtesting assets constructed using :class:`BacktestAsset`.

    Returns:
        A jit`ed `HashMapMarketDepthBacktest` that can be used in an ``njit`` function.
    """
    ptr = build_hashmap_backtest(assets)
    return HashMapMarketDepthBacktest_(ptr)


def ROIVectorMarketDepthBacktest(
    assets: list[BacktestAsset],
) -> ROIVectorMarketDepthBacktest_TypeHint:
    """
    Constructs an instance of `ROIVectorMarketBacktest`.

    Args:
        assets: A list of backtesting assets constructed using :class:`BacktestAsset`.

    Returns:
        A jit`ed `ROIVectorMarketBacktest` that can be used in an ``njit`` function.
    """
    ptr = build_roivec_backtest(assets)
    return ROIVectorMarketDepthBacktest_(ptr)


if LIVE_FEATURE:

    def ROIVectorMarketDepthLiveBot(
        assets: list[LiveInstrument],
    ) -> ROIVectorMarketDepthLiveBot_TypeHint:
        """
        Constructs an instance of `ROIVectorMarketDepthLiveBot`.

        Args:
            assets: A list of live instruments constructed using :class:`LiveInstrument`.

        Returns:
            A jit`ed `ROIVectorMarketDepthLiveBot` that can be used in an ``njit`` function.
        """
        ptr = build_roivec_livebot(assets)
        return ROIVectorMarketDepthLiveBot_(ptr)
