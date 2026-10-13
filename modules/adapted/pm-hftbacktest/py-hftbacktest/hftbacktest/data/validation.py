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


import sys

import numpy as np
from numba import njit
from numpy.typing import NDArray

from ..types import EVENT_ARRAY, EXCH_EVENT, LOCAL_EVENT, event_dtype


@njit
def correct_local_timestamp(data: EVENT_ARRAY, base_latency: float) -> EVENT_ARRAY:
    """
    Adjusts the local timestamp `in place` if the feed latency is negative by offsetting it by the maximum negative
    latency value as follows:

    .. code-block::

        feed_latency = local_timestamp - exch_timestamp
        adjusted_local_timestamp = local_timestamp + min(feed_latency, 0) + base_latency

    Args:
        data: Data to be corrected.
        base_latency: Due to discrepancies in system time between the exchange and the local machine, latency may be
                      measured inaccurately, resulting in negative latency values. The conversion process automatically
                      adjusts for positive latency but may still produce zero latency cases. By adding ``base_latency``,
                      more realistic values can be obtained. Unit should be the same as the feed data's timestamp unit.

    Returns:
        Data with the corrected timestamps.
    """

    latency = sys.maxsize
    for row_num in range(len(data)):
        exch_timestamp = data[row_num].exch_ts
        local_timestamp = data[row_num].local_ts

        latency = min(latency, local_timestamp - exch_timestamp)

    if latency < 0:
        local_timestamp_offset = -latency + base_latency
        print("local_timestamp is ahead of exch_timestamp by", -latency)
        for row_num in range(len(data)):
            data[row_num].local_ts += local_timestamp_offset

    return data


@njit
def correct_event_order(
    data: EVENT_ARRAY,
    sorted_exch_index: NDArray,
    sorted_local_index: NDArray,
) -> EVENT_ARRAY:
    """
    Corrects exchange timestamps that are reversed by splitting each row into separate events. These events are then
    ordered by both exchange and local timestamps through duplication.
    See the `data <https://hftbacktest.readthedocs.io/en/latest/data.html>`_ for details.

    Args:
        data: Data to be corrected.
        sorted_exch_index: Index of data sorted by exchange timestamp.
        sorted_local_index: Index of data sorted by local timestamp.

    Returns:
        Data with the corrected event order.
    """
    sorted_final = np.zeros(data.shape[0] * 2, event_dtype)

    out_rn = 0
    exch_rn = 0
    local_rn = 0
    while True:
        sorted_exch = data[sorted_exch_index[exch_rn]]
        sorted_local = data[sorted_local_index[local_rn]]
        if (
            exch_rn < len(data)
            and local_rn < len(data)
            and sorted_exch.exch_ts == sorted_local.exch_ts
            and sorted_exch.local_ts == sorted_local.local_ts
        ):
            assert sorted_exch.ev == sorted_local.ev
            assert (sorted_exch.px == sorted_local.px) or (
                np.isnan(sorted_exch.px) and np.isnan(sorted_local.px)
            )
            assert sorted_exch.qty == sorted_local.qty

            sorted_final[out_rn] = sorted_exch
            sorted_final[out_rn].ev = sorted_final[out_rn].ev | EXCH_EVENT | LOCAL_EVENT

            out_rn += 1
            exch_rn += 1
            local_rn += 1
        elif (
            exch_rn < len(data)
            and local_rn < len(data)
            and sorted_exch.exch_ts == sorted_local.exch_ts
            and sorted_exch.local_ts < sorted_local.local_ts
        ) or (exch_rn < len(data) and sorted_exch.exch_ts < sorted_local.exch_ts):
            # exchange
            sorted_final[out_rn] = sorted_exch
            sorted_final[out_rn].ev = sorted_final[out_rn].ev | EXCH_EVENT

            out_rn += 1
            exch_rn += 1
        elif (
            exch_rn < len(data)
            and local_rn < len(data)
            and sorted_exch.exch_ts == sorted_local.exch_ts
            and sorted_exch.local_ts > sorted_local.local_ts
        ) or (local_rn < len(data)):
            # local
            sorted_final[out_rn] = sorted_local
            sorted_final[out_rn].ev = sorted_final[out_rn].ev | LOCAL_EVENT

            out_rn += 1
            local_rn += 1
        elif exch_rn < len(data):
            # exchange
            sorted_final[out_rn] = sorted_exch
            sorted_final[out_rn].ev = sorted_final[out_rn].ev | EXCH_EVENT

            out_rn += 1
            exch_rn += 1
        else:
            assert exch_rn == len(data)
            assert local_rn == len(data)
            break
    return sorted_final[:out_rn]


def validate_event_order(data: EVENT_ARRAY) -> None:
    """
    Validates that the order of events is correct. If the data contains an incorrect event order, a :class:`ValueError`
    will be raised.

    Args:
        data: Data to validate.
    """
    exch_ev = data["ev"] & EXCH_EVENT == EXCH_EVENT
    local_ev = data["ev"] & LOCAL_EVENT == LOCAL_EVENT
    if np.sum(np.diff(data["exch_ts"][exch_ev]) < 0) > 0:
        raise ValueError("exchange events are out of order.")
    if np.sum(np.diff(data["local_ts"][local_ev]) < 0) > 0:
        raise ValueError("local events are out of order.")
