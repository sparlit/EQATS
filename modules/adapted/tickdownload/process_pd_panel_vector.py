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


"""
In this approach, we transpose a given panel and select the list of `items`
that we are interested in using `vector` methods.

Intuitively this approach is fast one. But we have seen a radically different
behavior on different data sizes, so we want to be able to profile both
approaches separately and see why something seems more expensive.

"""

import cProfile
import pstats
import time
from io import StringIO

import pandas as pd
from read_sql_data import get_hist_data_as_dataframes_dict
from tickerplot.sql.sqlalchemy_wrapper import get_metadata

metadata = get_metadata("sqlite:///nse_hist_data.sqlite3")


max_limit = 40
limit = 20
while limit < max_limit:
    scripdata_dict = get_hist_data_as_dataframes_dict(metadata=metadata, limit=limit)
    pan = pd.Panel(scripdata_dict)

    then0 = time.time()
    pr = cProfile.Profile()
    pr.enable()

    pan2 = pan.transpose(2, 0, 1)
    cl = pan2["close"]
    cl2 = cl[cl.iloc[:, -1] > cl.iloc[:, -2]]
    pan11 = pan[cl2.index]

    pr.disable()
    pr.dump_stats("vector.stats")
    s = StringIO()
    sort_by = "cumulative"
    ps = pstats.Stats(pr, stream=s).sort_stats(sort_by)
    ps.print_stats(0.1)
    now0 = time.time()

    # print (limit, now0 - then0)
    # print (len(cl2.index))
    # print (s.getvalue())

    limit *= 2
