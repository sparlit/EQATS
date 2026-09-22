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


""" The Entire idea is to evaluate the probablity distribution of a particular stock based on its out of the money options for the last day"""
import sys
from datetime import date, timedelta
from math import log, sqrt

import matplotlib.pyplot as plt
import MySQLdb
import numpy as np
from numpy.random import normal
from pandas.tseries.offsets import BDay
from scipy.stats import norm
from scipy.stats.kde import gaussian_kde
from SplineInterpVol import get_opt_vol_data

import config

if __name__ == "__main__":
    symbol = sys.argv[1]
    today = (date.today() - BDay(1)).__str__()
    data = get_opt_vol_data(symbol, today)

    def d_fun(x):
        return (
            log(x.FUT / x.STRIKE_PR)
            - 0.5
            * (x.VOLATILITY / 100.0)
            * (x.VOLATILITY / 100.0)
            * ((x.EXPIRY_DT - x.TIMESTAMP).total_seconds() / (365 * 24 * 60 * 60))
        ) / (0.01 * x.VOLATILITY * sqrt((x.EXPIRY_DT - x.TIMESTAMP).total_seconds() / (365 * 24 * 60 * 60)))

    def prob_fun(x):
        return norm.pdf(d_fun(x))

    data["PROBABLITY"] = data.apply(prob_fun, axis=1)
    kde = gaussian_kde(data.PROBABLITY)
    # range=np.arange(-5,5,0.05)
    # hist=kde.evaluate(range)
    plt.plot(data.STRIKE_PR, data.PROBABLITY)
    plt.show()
