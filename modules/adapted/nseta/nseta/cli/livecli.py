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
import click
from nseta.cli.inputs import *
from nseta.common.log import default_logger, tracelog
from nseta.resources.resources import *
from nseta.scanner.scannerFactory import *
from nseta.scanner.stockscanner import TECH_INDICATOR_KEYS, ScannerType

__all__ = ["live_quote", "scan", "top_picks"]


def split_keys(keystrings):
    keys = []
    for keystring in keystrings:
        kvp = keystring.split("=")
        if kvp[0] not in keys:
            keys.append(kvp[0])
    return keys


ORDER_BY_KEYS = split_keys(
    resources.scanner().intraday_scan_columns
    + resources.scanner().volume_scan_columns
    + resources.scanner().swing_scan_columns
    + resources.scanner().live_scan_columns
)


@click.command(help="Get live price quote of a security")
@click.option("--symbol", "-S", help="Security code.")
@click.option(
    "--general",
    "-g",
    default=False,
    is_flag=True,
    help="Get the general (Name, ISIN) details also (Optional)",
)
@click.option(
    "--ohlc", "-o", default=False, is_flag=True, help="Get the OHLC values also (Optional)"
)
@click.option(
    "--wk52",
    "-w",
    default=False,
    is_flag=True,
    help="Get the 52 week high/low values also (Optional)",
)
@click.option(
    "--volume",
    "-v",
    default=False,
    is_flag=True,
    help="Get the traded volume details also (Optional)",
)
@click.option(
    "--orderbook",
    "-b",
    default=False,
    is_flag=True,
    help="Get the current bid/offer details also (Optional)",
)
@click.option(
    "--background",
    "-r",
    default=False,
    is_flag=True,
    help="Keep running the process in the background (Optional)",
)
@tracelog
def live_quote(symbol, general, ohlc, wk52, volume, orderbook, background):
    if not validate_symbol(symbol):
        print_help_msg(live_quote)
        return
    scanner = scannerFactory.scanner(ScannerType.Quote)
    scanner.scan(symbol, general, ohlc, wk52, volume, orderbook, background)


@click.command(help="Scan live and intraday for prices and signals.")
@click.option(
    "--stocks",
    "-S",
    default=[],
    help="Comma separated security codes(Optional). When skipped, all stocks configured in stocks.txt will be scanned.)",
)
@click.option(
    "--live",
    "-l",
    default=False,
    is_flag=True,
    help="Scans (every min. when in background) the live-quote and lists those that meet the signal criteria. Works best with --background.",
)
@click.option(
    "--intraday",
    "-i",
    default=False,
    is_flag=True,
    help="Scans (every 10 sec when in background) the intraday price history and lists those that meet the signal criteria",
)
@click.option(
    "--swing",
    "-s",
    default=False,
    is_flag=True,
    help="Scans (every 10 sec when in background) the past 90 days price history and lists those that meet the signal criteria",
)
@click.option(
    "--volume",
    "-v",
    default=False,
    is_flag=True,
    help="Scans (every 10 sec when in background) the past 7 days price history and lists those that meet the signal criteria",
)
@click.option(
    "--indicator",
    "-t",
    default="all",
    type=click.Choice(TECH_INDICATOR_KEYS),
    help=", ".join(TECH_INDICATOR_KEYS) + ". Choose one.",
)
@click.option(
    "--orderby",
    "-o",
    type=click.Choice(ORDER_BY_KEYS),
    help=", ".join(ORDER_BY_KEYS) + ". Choose one.",
)
@click.option(
    "--clear",
    "-c",
    default=False,
    is_flag=True,
    help="Clears the cached data for the given options.",
)
@click.option(
    "--background",
    "-r",
    default=False,
    is_flag=True,
    help="Keep running the process in the background (Optional)",
)
@click.option(
    "--analyse",
    "-a",
    default=False,
    is_flag=True,
    help="Analyse to check which of the results have the best buy/sell confidence based on MACD (Optional)",
)
@tracelog
def scan(stocks, live, intraday, swing, volume, indicator, orderby, clear, background, analyse):
    args_list = [live, intraday, swing, volume]
    true_count = sum(args_list)
    if not validate_options(true_count, "--live, --intraday, --swing or --volume", scan):
        return
    stocks = get_stocks(stocks)
    try:
        scanner_type = (
            ScannerType.Volume
            if volume
            else (
                ScannerType.Intraday
                if intraday
                else (ScannerType.Swing if swing else ScannerType.Live)
            )
        )
        scanner = scannerFactory.scanner(scanner_type, stocks, indicator, background)
        scanner.clear_cache(clear, force_clear=False)
        scanner.scan(option=orderby, analyse=analyse)
    except Exception as e:
        log_error(e, scanner_type.name)
        return


@click.command(help="Scans for price action and signals for intraday or swing recommendations")
@click.option(
    "--stocks",
    "-S",
    default=[],
    help="Comma separated security codes(Optional). When skipped, all stocks configured in stocks.txt will be scanned.)",
)
@click.option(
    "--indicator",
    "-t",
    default="all",
    type=click.Choice(TECH_INDICATOR_KEYS),
    help=", ".join(TECH_INDICATOR_KEYS) + ". Choose one.",
)
@click.option(
    "--intraday",
    "-i",
    default=False,
    is_flag=True,
    help="Scans (every 10 sec when in background) the intraday price history and lists those that meet the signal criteria",
)
@click.option(
    "--swing",
    "-s",
    default=False,
    is_flag=True,
    help="Scans (every 10 sec when in background) the past 90 days price history and lists those that meet the signal criteria",
)
@click.option(
    "--clear",
    "-c",
    default=False,
    is_flag=True,
    help="Clears the cached data for the given options.",
)
@click.option(
    "--background",
    "-r",
    default=False,
    is_flag=True,
    help="Keep running the process in the background (Optional)",
)
@tracelog
def top_picks(stocks, intraday, swing, indicator, clear, background):
    args_list = [intraday, swing]
    true_count = sum(args_list)
    if not validate_options(true_count, "--intraday or --swing", top_picks):
        return

    stocks = get_stocks(stocks)
    try:
        scanner = scannerFactory.scanner(ScannerType.TopPick, stocks, indicator, background)
        scanner.clear_cache(clear, force_clear=False)
        scanner.scan()
    except Exception as e:
        log_error(e, "TopPicks")
        return


@click.command(help="Scans for news for the given tickers or all tickers from stocks.txt")
@click.option(
    "--stocks",
    "-S",
    default=[],
    help="Comma separated security codes(Optional). When skipped, all stocks configured in stocks.txt will be scanned.)",
)
@tracelog
def news(stocks):
    stocks = get_stocks(stocks)
    try:
        scanner = scannerFactory.scanner(ScannerType.News, stocks, None, False)
        scanner.clear_cache(True, force_clear=False)
        scanner.scan()
    except Exception as e:
        log_error(e, "News")
        return


def get_stocks(stocks):
    if stocks is not None and len(stocks) > 0:
        return [x.strip() for x in stocks.split(",")]
    else:
        return []


def log_error(e, scan_type):
    default_logger().debug(e, exc_info=True)
    click.secho(f"Failed to scan {scan_type}.\n", fg="red", nl=True)


def validate_options(true_count, options, func):
    if true_count > 1:
        click.secho(f"Choose only one of {options} options.", fg="red", nl=True)
        print_help_msg(func)
        return False
    elif true_count < 1:
        click.secho(f"Choose at least one of the {options} options.", fg="red", nl=True)
        print_help_msg(func)
        return False
    return True


"""
TODO:
1. Scan for stocks that have
  higher highs or V patterns of MOM, OBV, MACD, Price, RSI
  and RSI is bullish (50+).
  and Price is above EMA(9), SMA(10) and SMA(50)
  and MOM is +ve
  and OBV is +ve
  and MACD is > signal by a margin of x
  and volume is rising compared to 7day or yesterday's volume
"""
