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
from time import time

import click
from nseta.common.log import default_logger, tracelog
from nseta.jobs.dataDownloaderJob import *

__all__ = ["jobs"]

JOB_MAPPING = {
    "download": dataDownloaderJob,
}


@click.command(help="Starts or stops the jobs in the background")
@click.option(
    "--job",
    "-j",
    default="download",
    type=click.Choice(JOB_MAPPING),
    help=", ".join(JOB_MAPPING) + ". Choose one.",
)
@click.option(
    "--start",
    default=False,
    is_flag=True,
    help="By default(False). --start, if you would like the job to be started",
)
@click.option(
    "--stop",
    default=False,
    is_flag=True,
    help="By default(False). --stop, if you would like the job to be stopped",
)
@tracelog
def jobs(job, start, stop):
    start_time = time()
    try:
        downloadJob = dataDownloaderJob()
        if start:
            downloadJob.start()
        elif stop:
            downloadJob.stop()
        end_time = time()
        time_spent = end_time - start_time
        print(f"\nThis run of job took {time_spent:.1f} sec")
    except Exception as e:
        default_logger().debug(e, exc_info=True)
        click.secho("Failed to run the job. Please check the inputs.", fg="red", nl=True)
        return
    except SystemExit:
        pass
