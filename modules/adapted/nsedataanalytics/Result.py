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

import MySQLdb
import pandas as pd

import config
from config import down_fir, user_agent, wgt_comd

result_url = "http://www.nseindia.com/corporates/datafiles/BM_Next_1_Month.csv"


def get_result_data():
    global result_url
    down_file = "Result1M.csv"
    try:
        _wgt_comd = wgt_comd % (user_agent, down_fir + down_file, result_url)
        os.system(_wgt_comd)
        data = pd.read_csv(down_fir + down_file)
        db = MySQLdb.connect(config.host, config.user, config.password, "NSE")
        data.to_sql("RESULTS", con=db, flavor="mysql", if_exists="replace", chunksize=200)
    except:
        pass


if __name__ == "__main__":
    get_result_data()
