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
from hftbacktest import BUY_EVENT, EXCH_EVENT, LOCAL_EVENT, SELL_EVENT, event_dtype
from numba import njit
from numpy.typing import NDArray


@njit
def convert_(inp, ts_mul):
    out = np.zeros(len(inp), event_dtype)
    for i in range(len(inp)):
        ev = int(inp[i, 0])
        if inp[i, 3] == 1:
            ev |= BUY_EVENT
        elif inp[i, 3] == -1:
            ev |= SELL_EVENT
        if inp[i, 1] > 0:
            ev |= EXCH_EVENT
        if inp[i, 2] > 0:
            ev |= LOCAL_EVENT
        out[i].ev = ev
        out[i].exch_ts = inp[i, 1] * ts_mul
        out[i].local_ts = inp[i, 2] * ts_mul
        out[i].px = inp[i, 4]
        out[i].qty = inp[i, 5]
    return out


def convert(input_file: str, output_filename: str | None = None, ts_mul: float = 1000) -> NDArray:
    r"""
    Converts HftBacktest v1 data file into HftBacktest v2 data.

    Since v1 data uses `-1` in timestamps to indicate the invalidity of the event on that processor side, there will be
    a loss of timestamp information. Furthermore, it cannot check its validity due to this.
    Validity should be confirmed during the v1 generation.

    Args:
        input_file: Input filename for HftBacktest v1 data.
        output_filename: If provided, the converted data will be saved to the specified filename in ``npz`` format.
        ts_mul: The value is multiplied by the v1 format timestamp to adjust the timestamp unit.
                Typically, v1 uses microseconds, while v2 uses nanoseconds, so the default value is 1000.

    Returns:
        Converted data compatible with HftBacktest.
    """

    data_v1 = np.load(input_file)["data"]
    data_v2 = convert_(data_v1, ts_mul)

    if output_filename is not None:
        print(f"Saving to {output_filename}")
        np.savez_compressed(output_filename, data=data_v2)

    return data_v2
