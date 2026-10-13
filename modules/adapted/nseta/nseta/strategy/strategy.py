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


# -*- coding: utf-8 -*-
import logging

from nseta.backtests.backtester import *
from nseta.common.log import default_logger, tracelog  # suppress_stdout_stderr
from nseta.resources.resources import *

__VERBOSE__ = default_logger().level == logging.DEBUG
__all__ = [
    "backtest_custom_strategy",
    "backtest_ma_strategy",
    "backtest_rsi_strategy",
    "backtest_macd_strategy",
    "backtest_bbands_strategy",
    "backtest_multi_strategy",
]


@tracelog
def backtest_ma_strategy(
    df,
    fast_period=resources.backtest().smac_fast_period,
    slow_period=resources.backtest().smac_slow_period,
    plot=False,
    type_name="smac",
):
    resources.backtest()
    # ma_dict = {"smac":{"fast_period":bt.smac_fast_period, "slow_period":bt.smac_slow_period},
    #       "emac":{"fast_period":bt.emac_fast_period, "slow_period":bt.emac_slow_period}}
    return None


@tracelog
def backtest_rsi_strategy(
    df,
    rsi_period=resources.backtest().rsi_period,
    rsi_lower=resources.backtest().rsi_lower,
    rsi_upper=resources.backtest().rsi_upper,
    plot=False,
    type_name="rsi",
):
    return None


@tracelog
def backtest_macd_strategy(
    df,
    fast_period=resources.backtest().macd_fast_period,
    slow_period=resources.backtest().macd_slow_period,
    plot=False,
    type_name="macd",
):
    return None


@tracelog
def backtest_bbands_strategy(
    df,
    period=resources.backtest().bbands_period,
    devfactor=resources.backtest().bbands_devfactor,
    plot=False,
    type_name="bbands",
):
    return None


@tracelog
def backtest_multi_strategy(df, strats=None, plot=False, type_name="multi"):
    # if strats is None:
    #   strats = {
    #     "smac": {"fast_period": resources.backtest().multi_smac_fast_period_range, "slow_period": resources.backtest().multi_smac_slow_period_range},
    #     "rsi": {"rsi_lower": resources.backtest().multi_rsi_lower_range, "rsi_upper": resources.backtest().multi_rsi_upper_range},
    #   }
    return None


STRATEGY_FORECAST_MAPPING = {
    "rsi": backtest_rsi_strategy,
    "smac": backtest_ma_strategy,
    "macd": backtest_macd_strategy,
    "emac": backtest_ma_strategy,
    "bbands": backtest_bbands_strategy,
    "multi": backtest_multi_strategy,
}

STRATEGY_FORECAST_MAPPING_KEYS = list(STRATEGY_FORECAST_MAPPING.keys())


def backtest_custom_strategy(
    df,
    symbol,
    strategy,
    lower_limit=resources.forecast().lower,
    upper_limit=resources.forecast().upper,
    plot=False,
):
    return None
