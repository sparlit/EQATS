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


import numpy as np
from numpy.typing import NDArray

from ... import BacktestAsset, HashMapMarketDepthBacktest


def create_last_snapshot(
    data: list[str],
    tick_size: float,
    lot_size: float,
    initial_snapshot: str | None = None,
    output_snapshot_filename: str | None = None,
) -> NDArray:
    r"""
    Creates a snapshot of the last market depth for the specified data, which can be used as the initial snapshot data
    for subsequent data.

    Args:
         data: Data to be processed to obtain the last market depth snapshot.
         tick_size: Minimum price increment for the given asset.
         lot_size: Minimum order quantity for the given asset.
         initial_snapshot: The initial market depth snapshot.
         output_snapshot_filename: If provided, the snapshot data will be saved to the specified filename in ``npz``
                                   format.

    Returns:
        Snapshot of the last market depth compatible with HftBacktest.
    """
    # Just to reconstruct order book from the given snapshot to the end of the given data.
    asset = BacktestAsset().data(data).tick_size(tick_size).lot_size(lot_size)
    if initial_snapshot is not None:
        asset.initial_snapshot(initial_snapshot)

    hbt = HashMapMarketDepthBacktest([asset])

    # Go to the end of the data.
    if hbt._goto_end() not in [0, 1]:
        raise RuntimeError

    depth = hbt.depth(0)
    snapshot = depth.snapshot()
    snapshot_copied = snapshot.copy()
    depth.snapshot_free(snapshot)

    if output_snapshot_filename is not None:
        np.savez_compressed(output_snapshot_filename, data=snapshot_copied)

    return snapshot_copied
