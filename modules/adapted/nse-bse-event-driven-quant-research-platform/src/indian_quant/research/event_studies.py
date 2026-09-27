from __future__ import annotations

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


"""Event studies: announcement timestamps -> abnormal returns -> significance."""


from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class EventStudyResult:
    n_events: int
    window: tuple[int, int]
    mean_car: float
    median_car: float
    t_stat: float
    p_value: float
    car_by_offset: pd.DataFrame
    cars: object | None = None  # raw per-event CAR array for pooling


def event_study(
    returns: pd.Series,
    market_returns: pd.Series,
    event_times: pd.DatetimeIndex,
    *,
    pre: int = 5,
    post: int = 20,
) -> EventStudyResult:
    """Abnormal-return event study using a market-model-free (mean-adjusted) benchmark.

    ``returns`` and ``market_returns`` are aligned daily return series indexed
    by timestamp. CAR is summed over [t-pre, t+post] offsets around each event.
    """
    df = pd.DataFrame({"ret": returns, "mkt": market_returns}).sort_index()
    df["abnormal"] = df["ret"] - df["mkt"]
    index = df.index

    cars: list[float] = []
    paths: list[np.ndarray] = []
    used_events: list[pd.Timestamp] = []

    for event_time in event_times:
        pos = index.searchsorted(event_time)
        if pos < pre or pos + post >= len(df):
            continue
        window = df["abnormal"].iloc[pos - pre : pos + post + 1].to_numpy()
        if np.isnan(window).any():
            continue
        cars.append(float(window.sum()))
        paths.append(window)
        used_events.append(event_time)

    if not cars:
        return EventStudyResult(0, (pre, post), float("nan"), float("nan"), float("nan"), float("nan"), pd.DataFrame())

    arr = np.array(paths)
    car_series = np.array(cars)
    mean_car = float(car_series.mean())
    std = float(car_series.std(ddof=1)) if len(car_series) > 1 else float("nan")
    t_stat = mean_car / (std / np.sqrt(len(car_series))) if std and not np.isnan(std) else float("nan")

    from math import erf, sqrt

    def norm_sf(x: float) -> float:
        return 0.5 * (1.0 - erf(x / sqrt(2.0)))

    p_value = float(2.0 * norm_sf(abs(t_stat))) if not np.isnan(t_stat) else float("nan")

    by_offset = pd.DataFrame(
        {
            "offset": range(-pre, post + 1),
            "mean_abnormal": arr.mean(axis=0),
            "cum_mean_abnormal": arr.mean(axis=0).cumsum(),
        }
    )
    return EventStudyResult(
        len(cars), (pre, post), mean_car, float(np.median(car_series)), t_stat, p_value, by_offset, car_series
    )


def build_event_table(announcements_df: pd.DataFrame) -> pd.DatetimeIndex:
    """Extract event timestamps from an announcements frame."""
    ts = pd.to_datetime(announcements_df["published_at"], utc=True)
    return pd.DatetimeIndex(ts).sort_values()


__all__ = ["EventStudyResult", "build_event_table", "event_study"]
