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


import numpy as np
import pandas as pd

import config
from config import *

query = 'select bid,ask,ticklast,volume from fut_one_day where symbol=`$("%s-1M")'
all_data = pd.read_csv("C:/Users/ashish/Desktop/workspace/data/fut_one_day-2016.01.07.csv")


def intraday_buy_sell(symbol):
    with qconnection.QConnection(host=kdb_host, port=kdb_port):
        """data=qconn(query%(symbol))
        data=pd.DataFrame.from_records(data)"""
        global all_data
        data = all_data[all_data.symbol == (symbol + "-1M")]
        data[data.ticklast < (data.bid + data.ask) / 2].volume.sum()
        askvolume = data[data.ticklast > ((data.bid + data.ask) / 2)].volume.sum()
        liquidity = np.average((data.ask - data.bid) / ((data.ask + data.bid) / 2))
        return (
            (float(askvolume) / data.volume.sum()) * 100 if data.volume.sum() != 0 else 0,
            data.volume.sum(),
            liquidity,
        )


if __name__ == "__main__":
    all_buy = pd.DataFrame(columns=["SYMBOL", "AGG", "VOLUME", "LIQUIDITY"])
    for symbol in get_symbols():
        agg, volume, liquidity = intraday_buy_sell(symbol)

        all_buy = all_buy.append(
            {"SYMBOL": symbol, "AGG": agg, "VOLUME": volume, "LIQUIDITY": liquidity}, ignore_index=True
        )

    candidates = all_buy.sort(["LIQUIDITY", "VOLUME"], ascending=[True, False]).head(30)
    top_buy = candidates.sort("AGG", ascending=False).head(10)
