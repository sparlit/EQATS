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


from datetime import date, datetime, timedelta
from pathlib import Path

import click
from common.types import Venue
from inputs import get_download_functions
from service.App import *

"""
Download raw data for the specified venu and store udpates in the corresponding files.
If a file exists then new data will be appended (by overwriting some latest records).
If a file does not exist then all data will be downloaded and the file will be created.

The real connection and data retrieval is performed by venue-specific functions.
"""


@click.command()
@click.option("--config_file", "-c", type=click.Path(), default="", help="Configuration file name")
def main(config_file):
    """ """
    load_config(config_file)

    App.config["time_column"]
    Path(App.config["data_folder"])
    App.config["freq"]

    App.config.get("download_max_rows", 0)

    now = datetime.now()

    venue = App.config.get("venue")
    venue = Venue(venue)

    data_sources = App.config["data_sources"]

    download_klines_fn = get_download_functions(venue)

    # Call venue-specific downloader
    download_klines_fn(App.config, data_sources)

    elapsed = datetime.now() - now
    print()
    print(f"Finished downloading {len(data_sources)} data sources from {venue} in {str(elapsed).split('.')[0]}")


if __name__ == "__main__":
    main()
