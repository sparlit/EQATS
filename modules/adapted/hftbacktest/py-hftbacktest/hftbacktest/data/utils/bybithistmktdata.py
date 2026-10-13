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
import gzip
import json
from zipfile import ZipFile, is_zipfile

import numpy as np
from numpy.typing import NDArray

from ...types import (
    BUY_EVENT,
    DEPTH_CLEAR_EVENT,
    DEPTH_EVENT,
    DEPTH_SNAPSHOT_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
    event_dtype,
)
from .. import correct_event_order, validate_event_order
from ..validation import correct_local_timestamp


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
    Converts ByBit Historical Market Data files into a format compatible with HftBacktest.
    Since it doesn't have a local timestamp, it lacks feed latency information, which can result in a significant
    discrepancy between live and backtest results.
    Collecting feed data yourself or obtaining the high quality of data from a data vendor is strongly recommended.

    https://www.bybit.com/derivatives/en/history-data

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
    assert is_zipfile(depth_filename), "depth_file must be zip file provided by ByBit"
    assert trades_filename.endswith(".csv.gz"), "trades_file must be csv.gz file provided by ByBit"

    tmp = np.empty(buffer_size, event_dtype)
    row_num = 0

    orderbook_keys = ["a", "b"]

    print(f"Reading {depth_filename}")
    with ZipFile(depth_filename, "r") as zipfile, zipfile.open(zipfile.namelist()[0]) as f:
        for row in f:
            row: str = row.decode().strip()
            obj: object = json.loads(row)
            update_type: str = obj["type"]
            timestamp_ns: int = int(float(obj["ts"]) * 1_000_000)

            for key in orderbook_keys:
                if key in obj["data"]:
                    if update_type == "snapshot":
                        # Insert DEPTH_CLEAR_EVENT before DEPTH_SNAPSHOT_EVENT
                        tmp[row_num] = (
                            DEPTH_CLEAR_EVENT | (SELL_EVENT if key == "a" else BUY_EVENT),
                            timestamp_ns,
                            timestamp_ns + feed_latency,
                            obj["data"][key][-1][0],
                            0,
                            0,
                            0,
                            0,
                        )
                        row_num += 1

                    # Insert DEPTH_SNAPSHOT_EVENT or DEPTH_EVENT
                    for px, qty in obj["data"][key]:
                        tmp[row_num] = (
                            (
                                DEPTH_SNAPSHOT_EVENT
                                if update_type == "snapshot"
                                else DEPTH_EVENT | (SELL_EVENT if key == "a" else BUY_EVENT)
                            ),
                            timestamp_ns,
                            timestamp_ns + feed_latency,
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
    with gzip.open(trades_filename, mode="rt") as f:
        reader = csv.reader(f, delimiter=",")
        for row in reader:
            if timestamp_col is None:
                if trades_has_header is None:
                    trades_has_header = row[0] == "timestamp"

                if trades_has_header:
                    header = row
                else:
                    header = [
                        "timestamp",
                        "symbol",
                        "side",
                        "size",
                        "price",
                        "tickDirection",
                        "trdMatchID",
                        "grossValue",
                        "homeNotional",
                        "foreignNotional",
                    ]
                    if len(header) != len(row):
                        raise ValueError

                timestamp_col = header.index("timestamp")
                side_col = header.index("side")
                price_col = header.index("price")
                qty_col = header.index("size")

                if trades_has_header:
                    continue

            exch_ts = int(float(row[timestamp_col]) * 1_000_000_000)
            local_ts = exch_ts + feed_latency

            px = float(row[price_col])
            qty = float(row[qty_col])

            # Insert TRADE_EVENT
            tmp[row_num] = (
                TRADE_EVENT
                | (SELL_EVENT if row[side_col] == "Sell" else BUY_EVENT),  # trade initiator's side
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
