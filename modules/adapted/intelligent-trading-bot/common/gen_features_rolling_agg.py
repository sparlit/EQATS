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


import json
from datetime import datetime, timedelta, timezone
from decimal import *
from typing import List, Union

import dateparser
import numpy as np
import pandas as pd
from scipy import stats
from sklearn import linear_model


def add_past_weighted_aggregations(
    df,
    column_name: str,
    weight_column_name: str,
    fn,
    windows: int | list[int],
    suffix=None,
    rel_column_name: str | None = None,
    rel_factor: float = 1.0,
    last_rows: int = 0,
):
    return _add_weighted_aggregations(
        df, False, column_name, weight_column_name, fn, windows, suffix, rel_column_name, rel_factor, last_rows
    )


def add_past_aggregations(
    df,
    column_name: str,
    fn,
    windows: int | list[int],
    suffix=None,
    rel_column_name: str | None = None,
    rel_factor: float = 1.0,
    last_rows: int = 0,
):
    return _add_aggregations(df, False, column_name, fn, windows, suffix, rel_column_name, rel_factor, last_rows)


def add_future_aggregations(
    df,
    column_name: str,
    fn,
    windows: int | list[int],
    suffix=None,
    rel_column_name: str | None = None,
    rel_factor: float = 1.0,
    last_rows: int = 0,
):
    return _add_aggregations(df, True, column_name, fn, windows, suffix, rel_column_name, rel_factor, last_rows)
    # return _add_weighted_aggregations(df, True, column_name, None, fn, windows, suffix, rel_column_name, rel_factor, last_rows)


def _add_aggregations(
    df,
    is_future: bool,
    column_name: str,
    fn,
    windows: int | list[int],
    suffix=None,
    rel_column_name: str | None = None,
    rel_factor: float = 1.0,
    last_rows: int = 0,
):
    """
    Compute moving aggregations over past or future values of the specified base column using the specified windows.

    Windowing. Window size is the number of elements to be aggregated.
    For past aggregations, the current value is always included in the window.
    For future aggregations, the current value is not included in the window.

    Naming. The result columns will start from the base column name then suffix is used and then window size is appended (separated by underscore).
    If suffix is not provided then it is function name.
    The produced names will be returned as a list.

    Relative values. If the base column is provided then the result is computed as a relative change.
    If the coefficient is provided then the result is multiplied by it.

    The result columns are added to the data frame (and their names are returned).
    The length of the data frame is not changed even if some result values are None.
    """

    column = df[column_name]

    if isinstance(windows, int):
        windows = [windows]

    if rel_column_name:
        rel_column = df[rel_column_name]

    if suffix is None:
        suffix = "_" + fn.__name__

    features = []
    for w in windows:
        # Aggregate
        if not last_rows:
            feature = column.rolling(window=w, min_periods=max(1, w // 2)).apply(fn, raw=True)
        else:  # Only for last row
            feature = _aggregate_last_rows(column, w, last_rows, fn)

        # Convert past aggregation to future aggregation
        if is_future:
            feature = feature.shift(periods=-w)

        # Normalize
        feature_name = column_name + suffix + "_" + str(w)
        features.append(feature_name)
        if rel_column_name:
            df[feature_name] = rel_factor * (feature - rel_column) / rel_column
        else:
            df[feature_name] = rel_factor * feature

    return features


def _add_weighted_aggregations(
    df,
    is_future: bool,
    column_name: str,
    weight_column_name: str,
    fn,
    windows: int | list[int],
    suffix=None,
    rel_column_name: str | None = None,
    rel_factor: float = 1.0,
    last_rows: int = 0,
):
    """
    Weighted rolling aggregation. Normally using np.sum function which means area under the curve.
    """

    column = df[column_name]

    if weight_column_name:
        weight_column = df[weight_column_name]
    else:
        # If weight column is not specified then it is equal to constant 1.0
        weight_column = pd.Series(data=1.0, index=column.index)

    products_column = column * weight_column

    if isinstance(windows, int):
        windows = [windows]

    if rel_column_name:
        rel_column = df[rel_column_name]

    if suffix is None:
        suffix = "_" + fn.__name__

    features = []
    for w in windows:
        if not last_rows:
            # Sum of products
            feature = products_column.rolling(window=w, min_periods=max(1, w // 2)).apply(fn, raw=True)
            # Sum of weights
            weights = weight_column.rolling(window=w, min_periods=max(1, w // 2)).apply(fn, raw=True)
        else:  # Only for last row
            # Sum of products
            feature = _aggregate_last_rows(products_column, w, last_rows, fn)
            # Sum of weights
            weights = _aggregate_last_rows(weight_column, w, last_rows, fn)

        # Weighted feature
        feature = feature / weights

        # Convert past aggregation to future aggregation
        if is_future:
            feature = feature.shift(periods=-w)

        # Normalize
        feature_name = column_name + suffix + "_" + str(w)
        features.append(feature_name)
        if rel_column_name:
            df[feature_name] = rel_factor * (feature - rel_column) / rel_column
        else:
            df[feature_name] = rel_factor * feature

    return features


def add_area_ratio(df, is_future: bool, column_name: str, windows: int | list[int], suffix=None, last_rows: int = 0):
    """
    For past, we take this element and compare the previous sub-series: the area under and over this element
    For future, we take this element and compare the next sub-series: the area under and over this element
    """
    column = df[column_name]

    if isinstance(windows, int):
        windows = [windows]

    if suffix is None:
        suffix = "_" + "area_ratio"

    features = []
    for w in windows:
        if not last_rows:
            ro = column.rolling(window=w, min_periods=max(1, w // 2))
            feature = ro.apply(area_fn, kwargs={"is_future": is_future}, raw=True)
        else:  # Only for last row
            feature = _aggregate_last_rows(column, w, last_rows, area_fn, is_future)

        feature_name = column_name + suffix + "_" + str(w)

        if is_future:
            df[feature_name] = feature.shift(periods=-(w - 1))
        else:
            df[feature_name] = feature

        features.append(feature_name)

    return features


def area_fn(x, is_future):
    if is_future:
        level = x[0]  # Relative to the oldest element
    else:
        level = x[-1]  # Relative to the newest element
    x_diff = x - level  # Difference from the level
    a = np.nansum(x_diff)
    b = np.nansum(np.absolute(x_diff))
    pos = (b + a) / 2
    # neg = (b-a)/2
    ratio = pos / b  # in [0,1]
    return (ratio * 2) - 1  # scale to [-1,+1]


def add_linear_trends(df, is_future: bool, column_name: str, windows: int | list[int], suffix=None, last_rows: int = 0):
    """
    Use a series of points to compute slope of the fitted line and return it.
    For past, we use previous series.
    For future, we use future series.
    This point is included in series in both cases.
    """
    column = df[column_name]

    if isinstance(windows, int):
        windows = [windows]

    if suffix is None:
        suffix = "_" + "trend"

    features = []
    for w in windows:
        if not last_rows:
            ro = column.rolling(window=w, min_periods=max(1, w // 2))
            feature = ro.apply(slope_fn, raw=True)
        else:  # Only for last row
            feature = _aggregate_last_rows(column, w, last_rows, slope_fn)

        feature_name = column_name + suffix + "_" + str(w)

        if is_future:
            df[feature_name] = feature.shift(periods=-(w - 1))
        else:
            df[feature_name] = feature

        features.append(feature_name)

    return features


def slope_fn(x):
    """
    Given a Series, fit a linear regression model and return its slope interpreted as a trend.
    The sequence of values in X must correspond to increasing time in order for the trend to make sense.
    """
    X_array = np.asarray(range(len(x)))
    y_array = x
    if np.isnan(y_array).any():
        nans = ~np.isnan(y_array)
        X_array = X_array[nans]
        y_array = y_array[nans]

    # X_array = X_array.reshape(-1, 1)  # Make matrix
    # model = linear_model.LinearRegression()
    # model.fit(X_array, y_array)
    # slope = model.coef_[0]

    slope, _intercept, _r, _p, _se = stats.linregress(X_array, y_array)

    return slope


def to_log_diff(sr):
    return np.log(sr).diff()


def to_diff_NEW(sr):
    return 100 * sr.diff() / sr


def to_diff(sr):
    """
    Convert the specified input column to differences.
    Each value of the output series is equal to the difference between current and previous values divided by the current value.
    """

    def diff_fn(x):  # ndarray. last element is current row and first element is most old historic value
        return 100 * (x[1] - x[0]) / x[0]

    return sr.rolling(window=2, min_periods=2).apply(diff_fn, raw=True)


def _aggregate_last_rows(column, window, last_rows, fn, *args):
    """Rolling aggregation for only n last rows"""
    length = len(column)
    values = [fn(column.iloc[-window - r : length - r].to_numpy(), *args) for r in range(last_rows)]
    feature = pd.Series(data=np.nan, index=column.index, dtype=float)
    feature.iloc[-last_rows:] = list(reversed(values))
    return feature
