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
from hftbacktest import BacktestAsset, HashMapMarketDepthBacktest
from hftbacktest.data.utils import mexc
from numba import njit


@njit
def market_making_algo(hbt):
    while hbt.elapse(2.5e8) == 0:
        depth = hbt.depth(0)

        # Prints the best bid and the best offer.
        print(
            "current_timestamp:",
            hbt.current_timestamp,
            ", best_bid:",
            np.round(depth.best_bid, 1),
            ", best_ask:",
            np.round(depth.best_ask, 1),
        )
    return True


if __name__ == "__main__":
    data = mexc.convert(
        input_filename="examples/mexc/btcusdt_20250126.gz",
    )

    asset = (
        BacktestAsset()
        .data(data)
        .linear_asset(1.0)
        .power_prob_queue_model(2.0)
        .no_partial_fill_exchange()
        .trading_value_fee_model(-0.00005, 0.0007)
        .tick_size(0.1)
        .lot_size(0.001)
    )
    hbt = HashMapMarketDepthBacktest([asset])
    market_making_algo(hbt)
