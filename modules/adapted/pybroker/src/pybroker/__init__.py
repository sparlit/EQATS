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


"""Global imports."""

"""Copyright (C) 2023 Edward West. All rights reserved.

This code is licensed under Apache 2.0 with Commons Clause license
(see LICENSE for details).
"""

from pybroker.cache import (
    clear_caches as clear_caches,
)
from pybroker.cache import (
    clear_data_source_cache as clear_data_source_cache,
)
from pybroker.cache import (
    clear_indicator_cache as clear_indicator_cache,
)
from pybroker.cache import (
    clear_model_cache as clear_model_cache,
)
from pybroker.cache import (
    disable_caches as disable_caches,
)
from pybroker.cache import (
    disable_data_source_cache as disable_data_source_cache,
)
from pybroker.cache import (
    disable_indicator_cache as disable_indicator_cache,
)
from pybroker.cache import (
    disable_model_cache as disable_model_cache,
)
from pybroker.cache import (
    enable_caches as enable_caches,
)
from pybroker.cache import (
    enable_data_source_cache as enable_data_source_cache,
)
from pybroker.cache import (
    enable_indicator_cache as enable_indicator_cache,
)
from pybroker.cache import (
    enable_model_cache as enable_model_cache,
)
from pybroker.common import (
    BarData as BarData,
)
from pybroker.common import (
    DataCol as DataCol,
)
from pybroker.common import (
    Day as Day,
)
from pybroker.common import (
    FeeMode as FeeMode,
)
from pybroker.common import (
    OrderType as OrderType,
)
from pybroker.common import (
    PositionIntent as PositionIntent,
)
from pybroker.common import (
    PositionMode as PositionMode,
)
from pybroker.common import (
    PriceType as PriceType,
)
from pybroker.common import (
    StopType as StopType,
)
from pybroker.common import (
    SymbolSelector as SymbolSelector,
)
from pybroker.config import StrategyConfig as StrategyConfig
from pybroker.context import (
    ExecContext as ExecContext,
)
from pybroker.context import (
    IntervalContext as IntervalContext,
)
from pybroker.context import (
    RotationContext as RotationContext,
)
from pybroker.data import (
    Alpaca as Alpaca,
)
from pybroker.data import (
    AlpacaCrypto as AlpacaCrypto,
)
from pybroker.data import (
    YFinance as YFinance,
)
from pybroker.eval import (
    BootstrapResult as BootstrapResult,
)
from pybroker.eval import (
    EvalMetrics as EvalMetrics,
)
from pybroker.indicator import (
    Indicator as Indicator,
)
from pybroker.indicator import (
    IndicatorSet as IndicatorSet,
)
from pybroker.indicator import (
    IntervalBoundIndicator as IntervalBoundIndicator,
)
from pybroker.indicator import (
    highest as highest,
)
from pybroker.indicator import (
    indicator as indicator,
)
from pybroker.indicator import (
    lowest as lowest,
)
from pybroker.indicator import (
    returns as returns,
)
from pybroker.interval import (
    TimeframeInterval as TimeframeInterval,
)
from pybroker.interval import (
    compress_bars as compress_bars,
)
from pybroker.model import (
    IntervalBoundModel as IntervalBoundModel,
)
from pybroker.model import (
    ModelLoader as ModelLoader,
)
from pybroker.model import (
    ModelSource as ModelSource,
)
from pybroker.model import (
    ModelTrainer as ModelTrainer,
)
from pybroker.model import (
    model as model,
)
from pybroker.optimize import (
    Hyperparam as Hyperparam,
)
from pybroker.optimize import (
    OptimizeResult as OptimizeResult,
)
from pybroker.optimize import (
    WindowOptimizeResult as WindowOptimizeResult,
)
from pybroker.optimize import (
    hyperparam as hyperparam,
)
from pybroker.optimize import (
    make_objective as make_objective,
)
from pybroker.parallel import (
    ParallelConfig as ParallelConfig,
)
from pybroker.parallel import (
    get_parallel_config as get_parallel_config,
)
from pybroker.parallel import (
    set_parallel as set_parallel,
)
from pybroker.portfolio import (
    Entry as Entry,
)
from pybroker.portfolio import (
    Order as Order,
)
from pybroker.portfolio import (
    Position as Position,
)
from pybroker.portfolio import (
    Trade as Trade,
)
from pybroker.scope import (
    clear_params as clear_params,
)
from pybroker.scope import (
    disable_logging as disable_logging,
)
from pybroker.scope import (
    disable_progress_bar as disable_progress_bar,
)
from pybroker.scope import (
    enable_logging as enable_logging,
)
from pybroker.scope import (
    enable_progress_bar as enable_progress_bar,
)
from pybroker.scope import (
    param as param,
)
from pybroker.scope import (
    register_columns as register_columns,
)
from pybroker.scope import (
    unregister_columns as unregister_columns,
)
from pybroker.slippage import (
    FixedSlippageModel as FixedSlippageModel,
)
from pybroker.slippage import (
    SlippageContext as SlippageContext,
)
from pybroker.slippage import (
    SlippageModel as SlippageModel,
)
from pybroker.slippage import (
    VolatilitySlippageModel as VolatilitySlippageModel,
)
from pybroker.slippage import (
    VolumeSlippageModel as VolumeSlippageModel,
)
from pybroker.strategy import Strategy as Strategy
from pybroker.strategy import TestResult as TestResult
from pybroker.vect import (
    atr as atr,
)
from pybroker.vect import (
    cross as cross,
)
from pybroker.vect import (
    highv as highv,
)
from pybroker.vect import (
    lowv as lowv,
)
from pybroker.vect import (
    returnv as returnv,
)
from pybroker.vect import (
    sumv as sumv,
)

__version__ = "2.0.1"
