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

import click
from nseta.archives.archiver import *
from nseta.cli.inputs import *
from nseta.common.history import historicaldata
from nseta.common.log import default_logger, tracelog
from nseta.plots.plots import *

__all__ = ["plot_ta"]

PLOT_KEY_TO_FUNC = {
    "ALL": plot_technical_indicators,
    "PRICE": plot_history,
    "RSI": plot_rsi,
    "EMA": plot_ema,
    "SMA": plot_sma,
    "SSTO": plot_sstochastic,
    "FSTO": plot_fstochastic,
    "ADX": plot_adx,
    "MACD": plot_macd,
    "MOM": plot_mom,
    "DMI": plot_dmi,
    "OBV": plot_obv,
    "BBANDS": plot_bbands,
}
PLOT_TI_KEYS = list(PLOT_KEY_TO_FUNC.keys())


@click.command(help="Plot various technical analysis indicators")
@click.option("--symbol", "-S", help="Security code")
@click.option("--start", "-s", help="Start date in yyyy-mm-dd format")
@click.option("--end", "-e", help="End date in yyyy-mm-dd format")
@click.option(
    "--clear",
    "-c",
    default=False,
    is_flag=True,
    help="Clears the cached data for the given options.",
)
@click.option(
    "--plot-type", "-p", "plot_type", default="ALL", help=", ".join(PLOT_TI_KEYS) + ". Choose one."
)
@tracelog
def plot_ta(symbol, start, end, clear, plot_type="ALL"):
    if not validate_inputs(start, end, symbol):
        print_help_msg(plot_ta)
        return
    sd = datetime.strptime(start, "%Y-%m-%d").date()
    ed = datetime.strptime(end, "%Y-%m-%d").date()

    try:
        if clear:
            arch = archiver()
            arch.clearcache(response_type=ResponseType.History, force_clear=False)
        historyinstance = historicaldata()
        df = historyinstance.daily_ohlc_history(symbol, sd, ed, type=ResponseType.History)
        df.loc[:, "dt"] = df.loc[:, "Date"]
        df.set_index("Date", inplace=True)
        plot_type = plot_type.upper()
        if plot_type in PLOT_KEY_TO_FUNC:
            PLOT_KEY_TO_FUNC[plot_type](df).show()
        else:
            PLOT_KEY_TO_FUNC["ALL"](df).show()
        click.secho(f"Technical indicator(s): {plot_type}, plotted.", fg="green", nl=True)
    except Exception as e:
        default_logger().debug(e, exc_info=True)
        click.secho("Failed to plot technical indicators", fg="red", nl=True)
        return
    except SystemExit:
        pass
