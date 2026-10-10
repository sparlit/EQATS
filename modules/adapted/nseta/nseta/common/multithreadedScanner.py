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


# -*- coding: utf-8 -*-
import inspect

from nseta.common.commons import *
from nseta.common.log import default_logger, tracelog


@tracelog
def multithreaded_scan(**args):
    frame = inspect.currentframe()
    args, _, _, kwargs_main = inspect.getargvalues(frame)
    del kwargs_main["frame"]
    kwargs = kwargs_main["args"]
    items_segment = kwargs["items"]
    # Max number of items to be processed at a time by a thread
    n = kwargs["max_per_thread"]
    if len(items_segment) > n:
        kwargs1 = dict(kwargs)
        kwargs2 = dict(kwargs)
        first_n = items_segment[:n]
        remaining_items = items_segment[n:]
        # n_segmented_items = [items_segment[i * n:(i + 1) * n] for i in range((len(items_segment) + n - 1) // n )]
        kwargs1["items"] = first_n
        kwargs2["items"] = remaining_items
        t1 = ThreadReturns(
            target=multithreaded_scan, kwargs=kwargs1, name=f"{first_n[0]}-{first_n[-1]}"
        )
        t2 = ThreadReturns(
            target=multithreaded_scan,
            kwargs=kwargs2,
            name=f"{remaining_items[0]}-{remaining_items[-1]}",
        )
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        df1 = None
        df2 = None
        signaldf1 = None
        signaldf2 = None
        try:
            list1 = t1.result
            df1 = list1.pop(0)
            signaldf1 = list1.pop(0)
        except Exception as e:
            default_logger().debug(e, exc_info=True)

        try:
            list2 = t2.result
            df2 = list2.pop(0)
            signaldf2 = list2.pop(0)
        except Exception as e:
            default_logger().debug(e, exc_info=True)

        df = concatenated_dataframe(df1, df2)
        signaldf = concatenated_dataframe(signaldf1, signaldf2)
        return [df, signaldf]
    else:
        callbackMethod = kwargs["callbackMethod"]
        del kwargs["callbackMethod"]
        return callbackMethod(**kwargs)
