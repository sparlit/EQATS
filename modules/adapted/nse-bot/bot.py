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


import datetime as dt

import pandas as pd
from plyer import notification

from utils import *

icon = resource_path("logo.ico")  # Replace with the path to your icon


def bullish_pattern(data):
    data = data.tail(2)
    return bool(
        data.iloc[0]["Close"] < data.iloc[0]["Open"]
        and data.iloc[1]["Close"] > data.iloc[1]["Open"]
    )


def bearish_pattern(data):
    return bool(
        data.iloc[0]["Close"] > data.iloc[0]["Open"]
        and data.iloc[1]["Close"] < data.iloc[1]["Open"]
    )


def trading_hours():
    curr_time = dt.datetime.now().time()
    return bool(curr_time >= dt.time(9, 15) and curr_time <= dt.time(15, 30))


def calculate_indicators(data, k_period=6, d_period=3, ma_period=10, stdev_factor=2):
    # Calculate %K and %D values for stochastic oscillator
    highest_high = data["High"].rolling(k_period).max()
    lowest_low = data["Low"].rolling(k_period).min()
    k = 100 * (data["Close"] - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(d_period).mean()

    # Calculate Bollinger Bands
    bb_middle = data["Close"].rolling(ma_period).mean()
    bb_std = data["Close"].rolling(ma_period).std()
    bb_upper = bb_middle + stdev_factor * bb_std
    bb_lower = bb_middle - stdev_factor * bb_std

    # Add calculated indicators to the data
    data["%K"] = k
    data["%D"] = d
    data["BB_upper"] = bb_upper
    data["BB_middle"] = bb_middle
    data["BB_lower"] = bb_lower

    return data


def start_bot(event, stock="^NSEI", interval="1m"):

    while True:
        if event.is_set():
            break
        if trading_hours():
            data = get_live_data(stock, interval)
            data = calculate_indicators(data)
            data = strategy(data, symbol=stock)

            if isinstance(data, pd.core.frame.DataFrame):
                write_dataframe_to_excel(data, "NSE.xlsx")
            else:
                print(f"{stock} Waiting for signal...")


def strategy(data, symbol=""):
    for i in range(len(data)):
        if i >= 21:
            # Get current and previous %K and %D values
            curr_k = data.iloc[i]["%K"]
            prev_k = data.iloc[i - 1]["%K"]
            curr_d = data.iloc[i]["%D"]
            prev_d = data.iloc[i - 1]["%D"]
            now = dt.datetime.now().time()
            # Check for long entry condition
            if prev_k < prev_d and curr_k > curr_d and bullish_pattern(data):
                message = f"📈 Buy {symbol} entry {data.iloc[i]['Close']} exit {data.iloc[i]['BB_upper']} sl {data.iloc[i]['Low']}"
                notification.notify(title=f"{symbol} Signal 🤖", message=message)
                print(f"{symbol} Signal 🤖: {message}")
                return pd.DataFrame(
                    {
                        "Stock": symbol,
                        "Positions": "Buy",
                        "Entry": data.iloc[i]["Close"],
                        "Exit": data.iloc[i]["BB_upper"],
                        "Stop Loss": data.iloc[i]["Low"],
                        "Time": now,
                        "%K": data.iloc[i]["%K"],
                        "%D": data.iloc[i]["%D"],
                        "LTP": data.iloc[i]["Close"],
                    },
                    index=[0],
                )

            # Check for sell condition
            if prev_k > prev_d and curr_k < curr_d and bearish_pattern(data):
                message = f"📉 Sell {symbol} entry {data.iloc[i]['Close']} exit {data.iloc[i]['BB_lower']} sl {data.iloc[i]['High']}"
                notification.notify(title=f"{symbol} Signal 🤖", message=message)
                print(f"{symbol} Signal 🤖: {message}")
                return pd.DataFrame(
                    {
                        "Stock": symbol,
                        "Positions": "Sell",
                        "Entry": data.iloc[i]["Close"],
                        "Exit": data.iloc[i]["BB_lower"],
                        "Stop Loss": data.iloc[i]["High"],
                        "Time": now,
                        "%K": data.iloc[i]["%K"],
                        "%D": data.iloc[i]["%D"],
                        "LTP": data.iloc[i]["Close"],
                    },
                    index=[0],
                )

            return None
