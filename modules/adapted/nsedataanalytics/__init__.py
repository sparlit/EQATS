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


import MySQLdb
import pandas as pd
from CreateSymbolList import create_contract_list
from DivideHistoryInSymbol import create_fut_today
from GlobalData import update_global_data
from numpy import NaN
from pandas.tseries.offsets import BDay
from Result import get_result_data
from SplineInterpVol import perform_smile_skew_today
from VolSmileCalc import perform_calc_present

import config
from config import get_option_static_data_last_day, get_vol_data_last_day, update_all_tables

if __name__ == "__main__":
    db = MySQLdb.connect(config.host, config.user, config.password, "NSE")
    today = pd.datetime.today()
    data = get_option_static_data_last_day(today)
    # set_month_code(data)
    data.to_sql("FUT_OPT_LAST", db, flavor="mysql", if_exists="replace", chunksize=200)
    data = get_vol_data_last_day(today)
    data.to_sql("VOL_HIST", db, flavor="mysql", if_exists="append", chunksize=200)
    db.close()

    update_all_tables()

    perform_calc_present()
    perform_smile_skew_today()
    update_global_data()
    get_result_data()
    create_contract_list()
    create_fut_today()
