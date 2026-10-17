import cProfile
import datetime
import pstats
import time
from io import StringIO
from zoneinfo import ZoneInfo

import pandas as pd
import pytz
from read_sql_data import get_hist_data_as_dataframes_dict
from tickerplot.sql.sqlalchemy_wrapper import get_metadata


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = ZoneInfo("Asia/Kolkata")
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


class ProfileContext:
    """Context manager class for profiling code blocks with cProfile and pstats."""

    def __init__(self, sort_by="cumulative", print_fraction=0.1):
        self.sort_by = sort_by
        self.print_fraction = print_fraction
        self.profiler = cProfile.Profile()
        self.stream = StringIO()
        self.start_time = 0.0
        self.elapsed_time = 0.0
        self.stats = None
        self.stats_output = ""

    def __enter__(self):
        self.start_time = time.time()
        self.profiler.enable()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.profiler.disable()
        self.elapsed_time = time.time() - self.start_time
        self.stats = pstats.Stats(self.profiler, stream=self.stream).sort_stats(self.sort_by)
        self.stats.print_stats(self.print_fraction)
        self.stats_output = self.stream.getvalue()


def panel_bench_lc(panel):
    sels = [panel[x]["close"][-1] > panel[x]["close"][-2] for x in panel]
    return sels


def panel_bench_vector(panel):

    pan2 = panel.transpose(2, 0, 1)
    cl = pan2["close"]
    cl2 = cl[cl.iloc[:, -1] > cl.iloc[:, -2]]
    pan11 = panel[cl2.index]

    return pan11.items


class ProfilerContext:
    """Context manager for profiling code blocks using cProfile and printing performance metrics."""

    def __init__(self, label: int | str = 0, sort_by: str = "cumulative", fraction: float = 0.1):
        self.label = label
        self.sort_by = sort_by
        self.fraction = fraction
        self.profile = cProfile.Profile()
        self.start_time = 0.0
        self.elapsed_time = 0.0
        self.stats_str = ""
        self.result = None

    def __enter__(self):
        self.start_time = time.time()
        self.profile.enable()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.profile.disable()
        self.elapsed_time = time.time() - self.start_time
        stream = StringIO()
        ps = pstats.Stats(self.profile, stream=stream).sort_stats(self.sort_by)
        ps.print_stats(self.fraction)
        self.stats_str = stream.getvalue()

        print(self.label, self.elapsed_time)
        if self.result is not None:
            try:
                print(len(self.result))
            except TypeError:
                print(self.result)
        print(self.stats_str)
        return False


class ProcessPandasPanelBench:
    def __init__(self, method="cProfile", limit_rows=0, db_path=None):
        self.db_path = db_path
        self.method_name = method
        self.limit_rows = limit_rows
        self.metadata = get_metadata(self.db_path)

    def set_method(self, method_name="cProfile"):
        if method_name not in ("cprofile", "cProfile"):
            raise ValueError("Method name should be 'cProfile'")
        self.method_name = method_name

    def run_bench_cprofile(self, panel):
        with ProfileContext(sort_by="cumulative", print_fraction=0.1) as prof:
            selectors = panel_bench_lc(panel=panel)

        print(self.limit_rows, prof.elapsed_time)
        print(len(selectors))
        print(prof.stats_output)

        with ProfileContext(sort_by="cumulative", print_fraction=0.1) as prof:
            selectors = panel_bench_vector(panel=panel)

        print(self.limit_rows, prof.elapsed_time)
        print(len(selectors))
        print(prof.stats_output)

    def run_bench(self):

        # setup - common
        scripdata_dict = get_hist_data_as_dataframes_dict(
            metadata=self.metadata, limit=self.limit_rows
        )
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
        bench2 = ProcessPandasPanelBench(
            db_path="sqlite:///nse_hist_data.sqlite3", limit_rows=limit
        )
        bench2.run_bench()
        limit *= 2
