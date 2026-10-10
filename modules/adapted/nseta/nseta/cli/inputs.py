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
from datetime import datetime, timedelta

import click
from nseta.common.log import default_logger, tracelog

__all__ = ["validate_inputs", "print_help_msg", "validate_symbol"]

STRATEGY_DAYS_MAPPING = {
    "rsi": 20,
    "smac": 63,
    "macd": 50,
    "emac": 63,
    "bbands": 28,
    "multi": 63,
    "custom": 20,
}


@tracelog
def validate_inputs(start, end, symbol, strategy=None, skip_symbol=False):
    try:
        sd = datetime.strptime(start, "%Y-%m-%d").date()
        ed = datetime.strptime(end, "%Y-%m-%d").date()
        if strategy is not None:
            if timedelta(STRATEGY_DAYS_MAPPING[strategy.lower()]) > (ed - sd):
                click.secho(
                    "Please provide start and end date with a time delta of at least "
                    + str(STRATEGY_DAYS_MAPPING[strategy.lower()])
                    + " days for the selected strategy.",
                    fg="red",
                    nl=True,
                )
                return False
    except Exception as e:
        default_logger().debug(e, exc_info=True)
        click.secho("Please provide start and end date in format yyyy-mm-dd", fg="red", nl=True)
        return False
    except SystemExit:
        pass
    return True if skip_symbol else validate_symbol(symbol)


@tracelog
def print_help_msg(command):
    with click.Context(command) as ctx:
        click.echo(command.get_help(ctx))


@tracelog
def validate_symbol(symbol):
    if not symbol:
        click.secho("Please provide security/stock ticker", fg="red", nl=True)
        return False
    return True
