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
import os
import signal
import warnings

import click
import nseta
from nseta.archives.archiver import archiver
from nseta.cli.historycli import history, pe_history
from nseta.cli.jobscli import jobs
from nseta.cli.livecli import live_quote, news, scan, top_picks
from nseta.cli.modelcli import create_cdl_model
from nseta.cli.plotscli import plot_ta
from nseta.cli.strategycli import scan_trading_strategy, test_trading_strategy
from nseta.common import log
from nseta.common.log import default_logger

__all__ = ["nsetacli"]


@click.group(invoke_without_command=True, no_args_is_help=True)
@click.option(
    "--debug/--no-debug", default=False, help="--debug to turn debugging on. Default is off"
)
@click.option(
    "--resources",
    "-r",
    is_flag=True,
    help="Shows the resources directory path so you can navigate there and make changes to config and stocks list if you want to.",
)
@click.option("--version", "-v", is_flag=True, help="Shows the version of this library")
@click.option(
    "--trace/--no-trace",
    default=False,
    help="--trace to turn tracing on (works only with --debug). Default is off.",
)
@click.option(
    "--filter",
    "-f",
    default=None,
    help="--filter <TEXT> to show only logs that match the filter text. Works only with --debug",
)
def nsetacli(debug, resources, version, trace, filter):
    signal.signal(signal.SIGINT, sigint_handler)
    arch = archiver()
    log_file_path = os.path.join(arch.logs_directory, "logs.log")
    if os.path.exists(log_file_path):
        os.remove(log_file_path)
    if debug:
        click.echo("Debug mode is %s" % ("on" if debug else "off"))
        if trace:
            click.echo("Tracing mode is %s" % ("on" if trace else "off"))
        log.setup_custom_logger(
            "nseta", logging.DEBUG, trace, log_file_path=log_file_path, filter=filter
        )
    else:
        log.setup_custom_logger("nseta", logging.INFO, log_file_path=log_file_path)
    if version:
        click.echo(f"nseta {nseta.__version__}")
    if resources:
        click.echo(f"#### nseta {nseta.__version__} ####\n")
        click.echo(
            f'Please check the default "config.txt" and "stocks.txt" files and edit as per your needs. These are under: \n {arch.resources_directory}\n'
        )
        click.echo(
            f'If you would instead like to just scan for your own user defined stocks/tickers (as per NSE ticker name), please edit "userStocks.txt" file. This is under: \n {arch.userData_directory}\n'
        )
        click.echo(
            f"All the log files and stocks data is downloaded under: \n {arch.userData_directory}\n"
        )


@click.command(
    help="Force clears log files, downloaded contents etc. As good as a fresh install (with --deepclean option.)"
)
@click.option(
    "--deepclean",
    "-d",
    default=False,
    is_flag=True,
    help="--deepclean if you want all files removed.",
)
def clear(deepclean):
    arch = archiver()
    arch.clear_all(deep_clean=deepclean)
    if deepclean:
        click.secho(
            "Removed all log files, contents and downloaded/saved files.", fg="green", nl=True
        )
    else:
        click.secho("Removed top-level results that were saved earlier.", fg="yellow", nl=True)


nsetacli.add_command(clear)
nsetacli.add_command(create_cdl_model)
nsetacli.add_command(history)
nsetacli.add_command(jobs)
nsetacli.add_command(live_quote)
nsetacli.add_command(news)
nsetacli.add_command(pe_history)
nsetacli.add_command(plot_ta)
nsetacli.add_command(scan)
nsetacli.add_command(test_trading_strategy)
nsetacli.add_command(top_picks)
nsetacli.add_command(scan_trading_strategy)


def sigint_handler(signum, frame):
    warnings.filterwarnings("ignore")
    warnings.simplefilter("ignore")
    default_logger().debug("[sigint_handler] Keyboard Interrupt received. Exiting.")
    click.secho("[sigint_handler] Keyboard Interrupt received. Exiting.", fg="red", nl=True)
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


if __name__ == "__main__":
    nsetacli()
