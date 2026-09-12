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


"""Tests for multi-interval compression."""

import numpy as np
import pandas as pd
import pytest
from pybroker.common import DataCol, IndicatorSymbol
from pybroker.indicator import IndicatorsMixin, indicator
from pybroker.interval import (
    IntervalData,
    _normalize_duration_string,
    _validate_symbol_dates_for_base,
    build_compressed_symbol_df,
    compress,
    compress_bars,
    compress_intervals_from_frame,
    compress_symbol_df,
    compress_symbol_from_frame,
    compress_symbol_intervals_from_frame,
    compressed_bars_to_bar_data,
    format_interval,
    indicator_interval_name,
    is_valid_interval,
    lookahead_train_dates,
    model_interval_name,
    normalize_interval,
    parse_indicator_interval_name,
    parse_model_interval_name,
    slice_arrays_by_dates,
    slice_compressed_df_by_dates,
    validate_base_timeframe_data,
    validate_interval,
)
from pybroker.model import model
from pybroker.scope import StaticScope

from .fixtures import *


def _daily_bars(dates, o, h, low, c, v=None):
    n = len(dates)
    dates = np.array(dates, dtype="datetime64[D]")
    o = np.asarray(o, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    c = np.asarray(c, dtype=np.float64)
    v = np.ones(n, dtype=np.float64) if v is None else np.asarray(v, dtype=np.float64)
    return dates, o, h, low, c, v


def _minute_sym_df(periods: int = 390) -> pd.DataFrame:
    """Synthetic 1-minute OHLCV (~one trading day when periods=390)."""
    dates = pd.date_range("2020-01-06 09:30", periods=periods, freq="1min")
    close = np.linspace(100, 110, periods)
    return pd.DataFrame(
        {
            DataCol.DATE.value: dates,
            DataCol.OPEN.value: close,
            DataCol.HIGH.value: close + 0.5,
            DataCol.LOW.value: close - 0.5,
            DataCol.CLOSE.value: close,
            DataCol.VOLUME.value: np.ones(periods),
        }
    )


def _ohlcv_from_dates(dates: pd.DatetimeIndex) -> tuple:
    n = len(dates)
    close = np.arange(n, dtype=np.float64) + 1
    o = close
    h = close + 1
    low = close - 1
    v = np.ones(n)
    return (
        np.array(dates, dtype="datetime64[ns]"),
        o,
        h,
        low,
        close,
        v,
    )