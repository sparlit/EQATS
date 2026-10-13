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
from datetime import datetime
from time import time

import click
from nseta.archives.archiver import *
from nseta.cli.inputs import *
from nseta.common.history import *
from nseta.common.log import default_logger, tracelog
from nseta.resources.resources import *
from nseta.strategy.strategy import *
from nseta.strategy.strategyManager import *

__all__ = ["test_trading_strategy", "scan_trading_strategy"]

STRATEGY_MAPPING_KEYS = list(STRATEGY_MAPPING.keys()) + ["custom"]


@click.command(help="Measure the performance of your trading strategy")
@click.option("--symbol", "-S", help="Security code")
@click.option("--start", "-s", help="Start date in yyyy-mm-dd format")
@click.option("--end", "-e", help="End date in yyyy-mm-dd format")
@click.option(
    "--strategy",
    default="rsi",
    type=click.Choice(STRATEGY_MAPPING_KEYS),
    help=", ".join(STRATEGY_MAPPING_KEYS) + ". Choose one.",
)
@click.option(
    "--upper",
    "-u",
    default=resources.backtest().rsi_upper,
    type=float,
    help=f'Used as upper limit, for example, for RSI. Default is {str(resources.backtest().rsi_upper)}. Only when strategy is "custom", we buy the security when the predicted next day return is > + upper %',
)
@click.option(
    "--lower",
    "-l",
    default=resources.backtest().rsi_lower,
    type=float,
    help=f'Used as lower limit, for example, for RSI. Default is {str(resources.backtest().rsi_lower)}. Only when strategy is "custom", we sell the security when the predicted next day return is < - lower %',
)
@click.option(
    "--clear",
    "-c",
    default=False,
    is_flag=True,
    help="Clears the cached data for the given options.",
)
@click.option(
    "--plot",
    "-p",
    default=False,
    is_flag=True,
    help="By default(False). --plot, if you would like the results to be plotted.",
)
@click.option(
    "--strict",
    default=False,
    is_flag=True,
    help="By default(False). --strict, if you would like the buy/sell to be generated only at top/bottom reversals for the selected strategy.",
)
@click.option(
    "--intraday",
    "-i",
    is_flag=True,
    help="Test trading strategy for the current intraday price history (Optional)",
)
@tracelog
def test_trading_strategy(
    symbol, start, end, strategy, upper, lower, clear, plot, strict, intraday=False
):
    if not intraday:
        if not validate_inputs(start, end, symbol, strategy):
            print_help_msg(test_trading_strategy)
            return
        sd = datetime.strptime(start, "%Y-%m-%d").date()
        ed = datetime.strptime(end, "%Y-%m-%d").date()
    if not validate_symbol(symbol):
        print_help_msg(test_trading_strategy)
        return
    start_time = time()
    try:
        clear_cache(clear, intraday)
        sm = strategyManager()
        sm.strict = strict
        if intraday:
            sm.test_intraday_trading_strategy(symbol, strategy, lower, upper, plot=plot)
        else:
            sm.test_historical_trading_strategy(symbol, sd, ed, strategy, lower, upper, plot=plot)
        end_time = time()
        time_spent = end_time - start_time
        print(f"\nThis run of testing trading strategy took {time_spent:.1f} sec")
    except Exception as e:
        default_logger().debug(e, exc_info=True)
        click.secho("Failed to test trading strategy. Please check the inputs.", fg="red", nl=True)
        return
    except SystemExit:
        pass


@click.command(help="Test/Measure the performance of your trading strategy for multiple stocks")
@click.option(
    "--symbol",
    "-S",
    help="Comma separated security codes. Skip/Leave empty for scanning all stocks in stocks.txt.",
)
@click.option("--start", "-s", help="Start date in yyyy-mm-dd format")
@click.option("--end", "-e", help="End date in yyyy-mm-dd format")
@click.option(
    "--strategy",
    help=", ".join(STRATEGY_MAPPING_KEYS)
    + ". Choose one. Leave empty for scanning through all strategies.",
)
@click.option(
    "--upper",
    "-u",
    default=resources.rsi().upper,
    type=float,
    help=f'Used as upper limit, for example, for RSI. Default is {str(resources.rsi().upper)}. Only when strategy is "custom", we buy the security when the predicted next day return is > + upper %',
)
@click.option(
    "--lower",
    "-l",
    default=resources.rsi().lower,
    type=float,
    help=f'Used as lower limit, for example, for RSI. Default is {str(resources.rsi().lower)}. Only when strategy is "custom", we sell the security when the predicted next day return is < - lower %',
)
@click.option(
    "--clear",
    "-c",
    default=False,
    is_flag=True,
    help="Clears the cached data for the given options.",
)
@click.option(
    "--intraday",
    "-i",
    is_flag=True,
    help="Test trading strategy for the current intraday price history (Optional)",
)
@click.option(
    "--strict",
    default=False,
    is_flag=True,
    help="By default(False). --strict, if you would like the buy/sell to be generated only at top/bottom reversals for the selected strategy.",
)
@click.option(
    "--orderby",
    "-o",
    default="symbol",
    type=click.Choice(["symbol", "recommendation"]),
    help="symbol or recommendation. Choose one. Default is orderby symbol.",
)
@tracelog
def scan_trading_strategy(
    symbol, start, end, strategy, upper, lower, clear, orderby, strict, intraday=False
):
    if not intraday and not validate_inputs(start, end, symbol, None, skip_symbol=True):
        print_help_msg(scan_trading_strategy)
        return
    start_time = time()
    try:
        clear_cache(clear, intraday)
        sm = strategyManager()
        sm.strict = strict
        full_summary = sm.scan_trading_strategy(
            symbol, start, end, strategy, upper, lower, clear, orderby, intraday
        )
        end_time = time()
        time_spent = end_time - start_time
        print(f"\nThis run of trading strategy scan took {time_spent:.1f} sec")
        if full_summary is not None and len(full_summary) > 0:
            if strategy is not None:
                full_summary = full_summary.loc[
                    :, ["Symbol", f"{strategy.upper()}-PnL", f"Reco-{strategy.upper()}"]
                ]
            full_summary = full_summary.dropna()
            if orderby == "recommendation":
                full_summary = full_summary.sort_values(
                    by=f"Reco-{strategy.upper()}", ascending=True
                )
            print(f"\n{full_summary.to_string(index=False)}\n")
    except Exception as e:
        default_logger().debug(e, exc_info=True)
        click.secho("Failed to scan trading strategy. Please check the inputs.", fg="red", nl=True)
        return
    except SystemExit:
        pass


def clear_cache(clear, intraday=False):
    if clear:
        arch = archiver()
        arch.clearcache(
            response_type=ResponseType.Intraday if intraday else ResponseType.History,
            force_clear=False,
        )
