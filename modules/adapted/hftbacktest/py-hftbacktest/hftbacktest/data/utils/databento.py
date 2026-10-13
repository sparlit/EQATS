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


from typing import Literal

import databento as db
import numpy as np
import polars as pl
from numpy.typing import NDArray

from ...types import (
    ADD_ORDER_EVENT,
    BUY_EVENT,
    CANCEL_ORDER_EVENT,
    DEPTH_CLEAR_EVENT,
    FILL_EVENT,
    MODIFY_ORDER_EVENT,
    SELL_EVENT,
    TRADE_EVENT,
    event_dtype,
)
from ..validation import correct_event_order, correct_local_timestamp, validate_event_order


def convert(
    input_file: str,
    symbol: str | None,
    output_filename: str | None = None,
    base_latency: float = 0,
    file_type: Literal["mbo"] = "mbo",
) -> NDArray:
    r"""
    Converts a DataBento L3 Market-By-Order data file into a format compatible with HftBacktest.

    DataBento's historical data includes a Start-of-Day (SOD) snapshot for CME data. In the snapshot, the exchange
    timestamp represents the original time when the order was submitted, and the data is sorted in chronological order.
    This ensures that orders are built with the correct price-time priority. However, since these timestamps are in the
    past (before the clear message), the exchange timestamp is artificially set to the local timestamp to indicate the
    snapshot. This adjustment maintains the chronological order of exchange timestamps during multi-day backtesting.

    Args:
        input_file: DataBento's DBN file. e.g. *.mbo.dbn.zst
        symbol: Specify the symbol to process in the given file. If the file contains multiple symbols, the symbol
                should be provided; otherwise, the output file will contain mixed symbols.
        output_filename: If provided, the converted data will be saved to the specified filename in ``npz`` format.
        base_latency: The value to be added to the feed latency.
                      See :func:`.correct_local_timestamp`.
        file_type: Currently, only 'mbo' is supported.
    Returns:
        Converted data compatible with HftBacktest.
    """

    if file_type != "mbo":
        raise ValueError(f"{file_type} is unsupported")

    with open(input_file, "rb") as f:
        stored_data = db.DBNStore.from_bytes(f)

    # Convert to dataframe
    pd_df = stored_data.to_df()
    df = pl.DataFrame(pd_df).with_columns(pl.Series("ts_recv", pd_df.index))

    if symbol is not None:
        df = df.filter(pl.col("symbol") == symbol)

    df = df.select(["ts_event", "action", "side", "price", "size", "order_id", "flags", "ts_recv"])

    tmp = np.empty(len(df), event_dtype)

    snapshot_ts = False

    for rn, (ts_event, action, side, price, size, order_id, flags, ts_recv) in enumerate(
        df.iter_rows()
    ):
        exch_ts = int(ts_event.timestamp() * 1_000_000_000)
        local_ts = int(ts_recv.timestamp() * 1_000_000_000)

        if action == "A":
            ev = ADD_ORDER_EVENT
        elif action == "C":
            ev = CANCEL_ORDER_EVENT
        elif action == "M":
            ev = MODIFY_ORDER_EVENT
        elif action == "R":
            ev = DEPTH_CLEAR_EVENT
        elif action == "T":
            ev = TRADE_EVENT
        elif action == "F":
            ev = FILL_EVENT
        else:
            raise ValueError(action)

        if side == "B":
            ev |= BUY_EVENT
        elif side == "A":
            ev |= SELL_EVENT
        elif side == "N":
            pass
        else:
            raise ValueError(side)

        # Adjusts the timestamps for the snapshot.
        if ev == DEPTH_CLEAR_EVENT:
            snapshot_ts = local_ts
        if local_ts != snapshot_ts:
            snapshot_ts = None
        if snapshot_ts is not None:
            exch_ts = local_ts = snapshot_ts

        tmp[rn] = (ev, exch_ts, local_ts, price, size, order_id, flags, 0)

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
