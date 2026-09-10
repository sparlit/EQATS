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


"""Contains model related functionality."""


"""Copyright (C) 2023 Edward West. All rights reserved.

This code is licensed under Apache 2.0 with Commons Clause license
(see LICENSE for details).
"""

import functools
import inspect
import pickle
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    Optional,
    Union,
    cast,
)

import numpy as np
import pandas as pd
from joblib import delayed
from numba import njit

from pybroker.cache import CacheDateFields, ModelCacheKey
from pybroker.common import (
    DataCol,
    IndicatorSymbol,
    ModelSymbol,
    TrainedModel,
    get_unique_sorted_dates,
    to_datetime,
)
from pybroker.indicator import Indicator
from pybroker.interval import (
    IntervalData,
    TimeframeInterval,
    build_compressed_symbol_arrays,
    format_interval,
    lookahead_train_dates,
    normalize_intervals,
    parse_indicator_interval_name,
    parse_model_interval_name,
    slice_arrays_by_dates,
    validate_source_name,
)
from pybroker.parallel import _effective_n_jobs, parallel

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

    from numpy.typing import NDArray

    from pybroker.scope import SymbolArrayStore

# --- Model input and lag helpers (formerly timeseries.py) ---

ArrayDict = dict[str, np.ndarray]


@dataclass(frozen=True)
class LagSeriesKey:
    """Internal cache key for a full-history lagged series."""

    symbol: str
    column: str
    lag: int
    interval: str | None = None


LagSeriesCache = dict[LagSeriesKey, np.ndarray]


@dataclass
class ModelInput:
    """Internal numpy-backed model input with optional lag feature metadata.

    Not part of the public API. User-facing code receives
    :class:`pandas.DataFrame` instances materialized via
    :meth:`to_dataframe`, with any lag feature matrix passed explicitly as a
    separate :class:`numpy.ndarray` argument.
    """

    columns: tuple[str, ...]
    arrays: ArrayDict
    dates: np.ndarray
    lag_features: np.ndarray | None = None