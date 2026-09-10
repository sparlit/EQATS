from __future__ import annotations

import copy
import datetime
import json
import math
import warnings
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime as dt_datetime
from decimal import Decimal
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    Protocol,
    Union,
    cast,
)

import numpy as np
import optuna
import pandas as pd
import pytz
from joblib import delayed
from optuna.distributions import BaseDistribution, CategoricalDistribution
from optuna.samplers import BaseSampler, GridSampler, RandomSampler, TPESampler

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

from pybroker.scope import StaticScope


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


"""Hyperparameter declaration and optimization with Optuna.

Hyperparams declare tunable values for indicators and executions. Each
hyperparam is registered globally by name via :func:`hyperparam` and
resolved to a concrete int or float at backtest or optimization time.

Pass hyperparams as keyword arguments to
:func:`pybroker.indicator.indicator`, or list them on
:meth:`pybroker.strategy.Strategy.add_execution` to read them inside an
execution with ``ctx.hyperparam(name)``.
"""


"""Copyright (C) 2023 Edward West. All rights reserved.

This code is licensed under Apache 2.0 with Commons Clause license
(see LICENSE for details).
"""


@dataclass(frozen=True)
class Hyperparam:
    """Declares a named hyperparameter with bounds and step size.

    Created with :func:`hyperparam` and registered globally by ``name``.

    Attributes:
        name: Unique identifier used in indicator kwargs, execution
            hyperparam lists, and optimization results.
        default: Value for backtests and the baseline during optimization.
            Should lie within ``[low, high]``.
        low: Minimum candidate value searched during optimize (inclusive).
        high: Maximum candidate value searched during optimize (inclusive).
            Candidate values are ``low``, ``low + step``, ... up to the
            largest value not exceeding ``high``.
        step: Spacing between candidate values. Must be positive. Integer
            hyperparams use step=1.
    """

    name: str
    default: int | float
    low: int | float
    high: int | float
    step: int | float = 1
