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
import pandas as pd
import yfinance as yf
from curl_cffi import requests  # Without its Session object, yahoo will reject requests with YFRateLimitError

"""
Download quotes from Yahoo
"""


def download_klines(config, data_sources):
    """ """
    time_column = config["time_column"]
    data_path = Path(config["data_folder"])
    download_max_rows = config.get("download_max_rows", 0)

    now = datetime.now()

    # This session will be used in all requests to avoid YFRateLimitError
    session = requests.Session(impersonate="chrome")

    for ds in data_sources:
        # Assumption: folder name is equal to the symbol name we want to download
        quote = ds.get("folder")
        if not quote:
            print("ERROR. Folder is not specified.")
            continue

        # If file name is not specified then use symbol name as file name
        file = ds.get("file", quote)
        if not file:
            file = quote

        print(f"Start downloading '{quote}' ...")

        file_path = data_path / quote
        file_path.mkdir(parents=True, exist_ok=True)  # Ensure that folder exists

        file_name = (file_path / file).with_suffix(".csv")

        if file_name.is_file():
            df = pd.read_csv(file_name, parse_dates=[time_column], date_format="ISO8601")
            # df['Date'] = pd.to_datetime(df['Date'], format="ISO8601")  # "2022-06-07" iso format
            df[time_column] = df[time_column].dt.date
            last_date = df.iloc[-1][time_column]

            overlap = 2  # The overlap can be longer because the difference in days includes also weekends which are not trade days
            days = (pd.Timestamp(now) - pd.Timestamp(last_date)).days + overlap

            # === Download from the remote server
            # Download more data than we need and then overwrite the older data
            new_df = yf.download(quote, period=f"{days}d", auto_adjust=True, multi_level_index=False, session=session)

            new_df = new_df.reset_index()
            new_df["Date"] = pd.to_datetime(new_df["Date"], format="ISO8601", utc=True).dt.date
            # del new_df['Close']
            # new_df.rename({'Adj Close': 'Close'}, axis=1, inplace=True)
            new_df = new_df.rename({"Date": time_column}, axis=1)
            new_df.columns = new_df.columns.str.lower()

            df = pd.concat([df, new_df])
            df = df.drop_duplicates(subset=[time_column], keep="last")

        else:
            print("File not found. Full fetch...")

            # === Download from the remote server
            # df = yf.download(quote, date(1990, 1, 1), auto_adjust=True, multi_level_index=False)
            df = yf.download(quote, period="max", auto_adjust=True, multi_level_index=False, session=session)

            df = df.reset_index()
            df["Date"] = pd.to_datetime(df["Date"], format="ISO8601", utc=True).dt.date
            # del df['Close']
            # df.rename({'Adj Close': 'Close'}, axis=1, inplace=True)
            df = df.rename({"Date": time_column}, axis=1)
            df.columns = df.columns.str.lower()

            print("Full fetch finished.")

        df = df.sort_values(by=time_column)

        # Limit the saved size by only the latest rows
        if download_max_rows:
            df = df.tail(download_max_rows)

        df.to_csv(file_name, index=False)

        print(f"Finished downloading '{quote}'. Stored {len(df)} rows in '{file_name}'")
