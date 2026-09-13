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


from NseStockAnalyser.imports import *
from NseStockAnalyser.utils import *


def put_call_ratio(stock_code):
    nse = Nse()

    nse.get_fno_lot_sizes()[stock_code]  # If stock code not present, it will cause exception. will be caught by
    # continuation_handler

    data_json = get_raw_json_data(stock_code)["filtered"]
    call_data = data_json["CE"]
    put_data = data_json["PE"]

    return round(put_data["totOI"] / call_data["totOI"], 2), round(put_data["totVol"] / call_data["totVol"], 2)


@continuation_handler
def put_call_wrapper():
    code = input("Enter Stock Code : ")

    pc_oi, pc_vol = put_call_ratio(code.upper())

    print(f"P/C Ratio (Open Interest) : {pc_oi}")
    print(f"P/C Ratio (Volume) : {pc_vol}")
