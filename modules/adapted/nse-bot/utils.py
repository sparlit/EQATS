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


import os
import sys

import pandas as pd
import yfinance as yf

home_dir = os.path.expanduser("~")
bot_dir = os.path.join(home_dir, "NSE BOT")


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def write_dataframe_to_excel(dataframe, excel_file):

    if not os.path.exists(bot_dir):
        os.makedirs(bot_dir)

    excel_file_path = os.path.join(bot_dir, excel_file)

    if os.path.exists(excel_file_path):
        # Append the new dataframe to the existing Excel file
        with pd.ExcelWriter(
            excel_file_path, mode="a", engine="openpyxl", if_sheet_exists="overlay"
        ) as writer:
            last_sheet = writer.book.worksheets[-1]  # get the last sheet object
            startrow = last_sheet.max_row + 1  # get the next row to start writing at
            dataframe.to_excel(
                writer, header=False, startrow=startrow, index=False, engine="openpyxl"
            )

    else:
        dataframe.to_excel(excel_file_path, header=True, index=False, engine="openpyxl")


# Define function to get historical OHLC data from Yahoo Finance
def get_historical_data(symbol, start="2019-05-01", end="2023-05-01", interval="1d"):
    data = yf.download(symbol, start=start, end=end, interval=interval)
    return data


def get_live_data(symbol, interval="1m", period="1d"):
    ticker = yf.Ticker(symbol, session=None)
    data = ticker.history(interval=interval, period=period)
    return data
