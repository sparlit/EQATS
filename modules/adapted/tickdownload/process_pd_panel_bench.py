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
In this approach we are using `list comprehension` approach to filter data
based on certain criteria. Intuitively this should be slower than the
`vector` method.

We want to profile it for different datasets.
"""


import cProfile
import pstats
import time
from io import StringIO

import pandas as pd
from read_sql_data import get_hist_data_as_dataframes_dict
from tickerplot.sql.sqlalchemy_wrapper import get_metadata


def panel_bench_lc(panel):
    return [panel[x]["close"][-1] > panel[x]["close"][-2] for x in panel]


def panel_bench_vector(panel):

    pan2 = panel.transpose(2, 0, 1)
    cl = pan2["close"]
    cl2 = cl[cl.iloc[:, -1] > cl.iloc[:, -2]]
    pan11 = panel[cl2.index]

    return pan11.items


class ProcessPandasPanelBench:
    def __init__(self, method="cProfile", limit_rows=0, db_path=None):
        self.db_path = db_path
        self.method_name = method
        self.limit_rows = limit_rows
        self.metadata = get_metadata(self.db_path)

    def set_method(self, method_name="cProfile"):
        if method_name != "cprofile":
            msg = "Method name should be 'cProfile'"
            raise ValueError(msg)
        self.method_name = method_name

    def run_bench_cprofile(self, panel):

        # FIXME: Add a Contextanager Class
        then0 = time.time()
        pr = cProfile.Profile()
        pr.enable()

        selectors = panel_bench_lc(panel=panel)

        pr.disable()
        s = StringIO()
        sort_by = "cumulative"
        ps = pstats.Stats(pr, stream=s).sort_stats(sort_by)
        ps.print_stats(0.1)

        now0 = time.time()

        print(self.limit_rows, now0 - then0)
        print(len(selectors))
        print(s.getvalue())

        # FIXME: Add a Contextanager Class
        then0 = time.time()
        pr = cProfile.Profile()
        pr.enable()

        selectors = panel_bench_vector(panel=panel)

        pr.disable()
        s = StringIO()
        sort_by = "cumulative"
        ps = pstats.Stats(pr, stream=s).sort_stats(sort_by)
        ps.print_stats(0.1)

        now0 = time.time()

        print(self.limit_rows, now0 - then0)
        print(len(selectors))
        print(s.getvalue())

    def run_bench(self):

        # setup - common
        scripdata_dict = get_hist_data_as_dataframes_dict(metadata=self.metadata, limit=self.limit_rows)
        panel = pd.Panel(scripdata_dict)

        print(panel)
        self.run_bench_cprofile(panel)


if __name__ == "__main__":
    # bench = ProcessPandasPanelBench(db_path='sqlite:///nse_hist_data_test2.sqlite3',
    #                                limit_rows=0)
    # bench.run_bench()
    print("*" * 80)
    limit = 20
    while limit <= 4000:
        bench2 = ProcessPandasPanelBench(db_path="sqlite:///nse_hist_data.sqlite3", limit_rows=limit)
        bench2.run_bench()
        limit *= 2
