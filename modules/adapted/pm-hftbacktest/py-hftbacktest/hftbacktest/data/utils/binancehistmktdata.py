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


import csv

import numpy as np
from numpy.typing import NDArray

from ...types import (
    BUY_EVENT,
    DEPTH_EVENT,
    DEPTH_SNAPSHOT_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
    event_dtype,
)
from .. import correct_event_order, validate_event_order
from ..validation import correct_local_timestamp


def convert_snapshot(
    snapshot_filename: str,
    output_filename: str | None = None,
    feed_latency: float = 0,
    has_header: bool | None = None,
    ss_buffer_size: int = 1_000_000,
) -> NDArray:
    r"""
    Converts Binance Historical Market Data files into a format compatible with HftBacktest.
    Since it doesn't have a local timestamp, it lacks feed latency information, which can result in a significant
    discrepancy between live and backtest results.
    Collecting feed data yourself or obtaining the high quality of data from a data vendor is strongly recommended.

    https://www.binance.com/en/landing/data

    Args:
        snapshot_filename: Snapshot filename
        output_filename: If provided, the converted data will be saved to the specified filename in ``npz`` format.
        feed_latency: Artificial feed latency value to be added to the exchange timestamp to create local timestamp.
        has_header: True if the given file has a header, it will automatically detect it if set to None.

    Returns:
        Converted data compatible with HftBacktest.
    """
    ss_bid = np.empty(ss_buffer_size, event_dtype)
    ss_ask = np.empty(ss_buffer_size, event_dtype)
    ss_bid_rn = 0
    ss_ask_rn = 0

    timestamp_col = None
    side_col = None
    price_col = None
    qty_col = None

    # Reads snapshot file
    print(f"Reading {snapshot_filename}")
    with open(snapshot_filename, newline="") as f:
        reader = csv.reader(f, delimiter=",")
        for row in reader:
            if timestamp_col is None:
                if has_header is None:
                    has_header = row[0] == "symbol"

                if has_header:
                    header = row
                else:
                    header = [
                        "symbol",
                        "timestamp",
                        "trans_id",
                        "first_update_id",
                        "last_update_id",
                        "side",
                        "update_type",
                        "price",
                        "qty",
                    ]
                    if len(header) != len(row):
                        raise ValueError

                timestamp_col = header.index("timestamp")
                side_col = header.index("side")
                price_col = header.index("price")
                qty_col = header.index("qty")

                if has_header:
                    continue

            exch_ts = int(row[timestamp_col])
            local_ts = exch_ts + feed_latency
            side = 1 if row[side_col] == "b" else -1
            price = float(row[price_col])
            qty = float(row[qty_col])

            if side == 1:
                ss_bid[ss_bid_rn] = (
                    DEPTH_SNAPSHOT_EVENT | BUY_EVENT,
                    exch_ts,
                    local_ts,
                    price,
                    qty,
                    0,
                    0,
                    0,
                )
                ss_bid_rn += 1
            else:
                ss_ask[ss_ask_rn] = (
                    DEPTH_SNAPSHOT_EVENT | SELL_EVENT,
                    exch_ts,
                    local_ts,
                    price,
                    qty,
                    0,
                    0,
                    0,
                )
                ss_ask_rn += 1

    ss_bid = ss_bid[:ss_bid_rn]
    ss_ask = ss_ask[:ss_ask_rn]
    snapshot = np.empty(len(ss_bid) + len(ss_ask), event_dtype)

    snapshot[: len(ss_bid)] = sorted(ss_bid, key=lambda v: -float(v[4]))
    snapshot[len(ss_bid) : len(ss_bid) + len(ss_ask)] = sorted(ss_ask, key=lambda v: float(v[4]))

    if output_filename is not None:
        np.savez(output_filename, data=snapshot)

    return snapshot


def convert(
    depth_filename: str,
    trades_filename: str,
    output_filename: str | None = None,
    buffer_size: int = 100_000_000,
    feed_latency: float = 0,
    base_latency: float = 0,
    depth_has_header: bool | None = None,
    trades_has_header: bool | None = None,
) -> NDArray:
    r"""
    Converts Binance Historical Market Data files into a format compatible with HftBacktest.
    Since it doesn't have a local timestamp, it lacks feed latency information, which can result in a significant
    discrepancy between live and backtest results.
    Collecting feed data yourself or obtaining the high quality of data from a data vendor is strongly recommended.

    https://www.binance.com/en/landing/data

    Args:
        depth_filename: Depth data filename
        trades_filename: Trades data filename
        output_filename: If provided, the converted data will be saved to the specified filename in ``npz`` format.
        buffer_size: Sets a preallocated row size for the buffer.
        feed_latency: Artificial feed latency value to be added to the exchange timestamp to create local timestamp.
        base_latency: The value to be added to the feed latency.
                      See :func:`.correct_local_timestamp`.
        method: The method to correct reversed exchange timestamp events. See :func:`..validation.correct`.
        depth_has_header: True if the given file has a header, it will automatically detect it if set to None.
        trades_has_header: True if the given file has a header, it will automatically detect it if set to None.

    Returns:
        Converted data compatible with HftBacktest.
    """
    tmp = np.empty(buffer_size, event_dtype)
    row_num = 0

    timestamp_col = None
    side_col = None
    price_col = None
    qty_col = None

    print(f"Reading {depth_filename}")
    with open(depth_filename, newline="") as f:
        reader = csv.reader(f, delimiter=",")
        for row in reader:
            if timestamp_col is None:
                if depth_has_header is None:
                    depth_has_header = row[0] == "symbol"

                if depth_has_header:
                    header = row
                else:
                    header = [
                        "symbol",
                        "timestamp",
                        "trans_id",
                        "first_update_id",
                        "last_update_id",
                        "side",
                        "update_type",
                        "price",
                        "qty",
                    ]
                    if len(header) != len(row):
                        raise ValueError

                timestamp_col = header.index("timestamp")
                side_col = header.index("side")
                price_col = header.index("price")
                qty_col = header.index("qty")

                if depth_has_header:
                    continue

            exch_ts = int(row[timestamp_col])
            local_ts = exch_ts + feed_latency
            px = float(row[price_col])
            qty = float(row[qty_col])

            # Insert DEPTH_EVENT
            tmp[row_num] = (
                DEPTH_EVENT | (BUY_EVENT if row[side_col] == "b" else SELL_EVENT),
                exch_ts,
                local_ts,
                px,
                qty,
                0,
                0,
                0,
            )
            row_num += 1

    timestamp_col = None
    side_col = None
    price_col = None
    qty_col = None

    print(f"Reading {trades_filename}")
    with open(trades_filename, newline="") as f:
        reader = csv.reader(f, delimiter=",")
        for row in reader:
            if timestamp_col is None:
                if trades_has_header is None:
                    trades_has_header = row[0] == "id"

                if trades_has_header:
                    header = row
                else:
                    header = ["id", "price", "qty", "quote_qty", "time", "is_buyer_maker"]
                    if len(header) != len(row):
                        raise ValueError

                timestamp_col = header.index("time")
                side_col = header.index("is_buyer_maker")
                price_col = header.index("price")
                qty_col = header.index("qty")

                if trades_has_header:
                    continue

            exch_ts = int(row[timestamp_col])
            local_ts = exch_ts + feed_latency

            px = float(row[price_col])
            qty = float(row[qty_col])

            # Insert TRADE_EVENT
            tmp[row_num] = (
                TRADE_EVENT
                | (SELL_EVENT if row[side_col] else BUY_EVENT),  # trade initiator's side
                exch_ts,
                local_ts,
                px,
                qty,
                0,
                0,
                0,
            )
            row_num += 1
    tmp = tmp[:row_num]

    print("Correcting the latency")
    tmp = correct_local_timestamp(tmp, base_latency)

    print("Correcting the event order")
    data = correct_event_order(
        tmp,
        np.argsort(tmp["exch_ts"], kind="mergesort"),
        np.argsort(tmp["local_ts"], kind="mergesort"),
    )

    validate_event_order(data)

    if output_filename is not None:
        print(f"Saving to {output_filename}")
        np.savez_compressed(output_filename, data=data)

    return data
