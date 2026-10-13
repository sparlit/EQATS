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


import os
import sys

root = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
)
sys.path.append(root)

from ccxt.pro.test.base.test_abnormal_close import test_abnormal_close  # noqa: F401
from ccxt.pro.test.base.test_cache import test_ws_cache  # noqa: F401
from ccxt.pro.test.base.test_cache_native import (
    test_ws_cache_python_regressions,  # noqa: F401  # hand-written python-only
)
from ccxt.pro.test.base.test_client_reset import (
    test_ws_client_reset,  # noqa: F401  # hand-written python-only
)

# todo : from ccxt.pro.test.base.test_close import test_ws_close  # noqa: F401
from ccxt.pro.test.base.test_future import test_ws_future  # noqa: F401
from ccxt.pro.test.base.test_order_book import test_ws_order_book  # noqa: F401


async def test_base_init_ws():
    test_ws_order_book()
    test_ws_cache()
    test_ws_cache_python_regressions()  # hand-written python-only
    # todo : run(test_ws_close())
    await test_ws_future()
    await test_ws_client_reset()  # hand-written python-only
    # run(test_abnormal_close()) stays in infinite loop in travis
