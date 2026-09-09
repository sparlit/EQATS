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
from datetime import date, datetime

import pandas as pd


def mkeywords(df):
    path = os.getcwd() + "data/keywords.txt"
    print(path)
    df.copy()
    f = open(path)
    allKeywords = f.read().lower().split("\n")
    f.close()
    print(allKeywords)
    """
    output_set = set()
    for var in df["More Info"]:
        if var == keywords:
            output_set.add(set)
    """
    return df["More Info"]


if __name__ == "__main__":
    dt = datetime.now().date()
    fd = datetime.strptime(str(dt), "%Y-%m-%d").date()
    base_path = os.getcwd() + "/data/BSE_{}_{}"
    path_csv = base_path.format(fd, fd) + ".csv"
    print(path_csv)
    df = pd.read_csv(path_csv)
    dfnew = mkeywords(df)
    print(dfnew)
