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


import functools
import json
import random
import string
import time
from datetime import datetime
from pathlib import Path

import matplotlib.dates as mdates
import pandas as pd
from matplotlib import ticker
from matplotlib.axes import Axes


class DateEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def load_json(fpath: Path):
    return json.loads(fpath.read_text(encoding="utf-8-sig"))


def write_json(fpath: Path, data):
    fpath.write_text(
        json.dumps(data, indent=2, cls=DateEncoder),
        encoding="utf-8",
    )


def index_to_iso(x: float, index: pd.DatetimeIndex) -> str:
    return index[round(x)].date().isoformat()


def iso_to_index(date: str, index: pd.DatetimeIndex) -> float:
    ts = pd.Timestamp(date)
    if ts in index:
        idx = index.get_loc(ts)

        if not isinstance(idx, int):
            msg = f"Expected int got {type(idx)}"
            raise ValueError(msg)

        return float(idx)
    return float(index.get_indexer([ts], method="nearest")[0])


def randomChar(length):
    return "".join(random.choice(string.ascii_lowercase) for _ in range(length))


def debounce(interval: float = 0.025):
    """Decorator that skips calls made within `interval` seconds.

    If a call is skipped, the most recent result is returned.
    """

    def decorator(func):
        last_call = 0.0
        last_result = None

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal last_call, last_result

            now = time.monotonic()

            if now - last_call < interval:
                return last_result if last_result is not None else ""

            last_result = func(*args, **kwargs)
            last_call = now
            return last_result

        return wrapper

    return decorator


def setup_xaxis(ax: Axes, df: pd.DataFrame) -> None:
    """Configure x-axis with ConciseDateFormatter and AutoDateLocator."""
    locator = mdates.AutoDateLocator(minticks=3, maxticks=7)

    concise_formatter = mdates.ConciseDateFormatter(locator=locator)

    tick_mdates = locator.tick_values(df.index[0], df.index[-1])
    labels = concise_formatter.format_ticks(tick_mdates)
    ticks = get_tick_locs(tick_mdates, df.index)

    fixed_formatter = ticker.FixedFormatter(labels)
    fixed_locator = ticker.FixedLocator(ticks)
    fixed_formatter.set_offset_string(concise_formatter.get_offset())

    ax.xaxis.set_major_locator(fixed_locator)
    ax.xaxis.set_major_formatter(fixed_formatter)


def get_tick_locs(
    tick_mdates,
    dtix: pd.DatetimeIndex,
) -> list[int]:
    """
    Return tick locations as integer indices matching DataFrame positions.
    """
    ticks: list[int] = []
    for dt in mdates.num2date(tick_mdates):
        dt = dt.replace(tzinfo=None)
        idx = dtix.get_loc(dt) if dt in dtix else dtix.searchsorted(dt, side="right")
        ticks.append(idx)
    return ticks
