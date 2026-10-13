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


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar 18 01:54:22 2018

@author: pujan
"""

import pandas as pd
from numpy import nan as Nan

f = pd.read_csv("StockNews.csv")
d = pd.read_csv("Data.csv")

X = d.iloc[:, 0]
y = d.iloc[:, 1]
f = pd.DataFrame(
    Nan, index=range(0, 63), columns=["Date", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
)
Z = X.drop_duplicates(keep="first")
# f.iloc[9, 0]
for i in range(0, 63):
    f.iloc[i, 0] = Z.iloc[i]

k = 0
for j in range(0, 63):
    for i in range(1, 11):
        f.iloc[j, i] = y.iloc[k]
        k += 1
data1 = pd.read_csv("final.csv")
"""
d = np.array(d, dtype='str')
for i in range(0, 640):
    print(d[i][0])
    print(d[i][1])
    news.append(d[i][0])

news"""
