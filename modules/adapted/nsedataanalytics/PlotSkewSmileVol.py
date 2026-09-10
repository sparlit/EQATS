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


import math
import sys

import matplotlib.pyplot as plt
import MySQLdb
import pandas as pd

import config

if __name__ == "__main__":
    symbol = sys.argv[1]
    db = MySQLdb.connect(config.host, config.user, config.password, "NSE")
    """Also add the Volume and the underlying Stock price """
    sql = 'select TIME,ATM_VOL,SMILE,SKEW,SETTLE_PR,CONTRACTS from ATM_SKEW_SMILE_HIST a,%s b\
        where a.TIME=b.TIMESTAMP and\
        a.symbol="%s" and (b.INSTRUMENT="FUTIDX" or b.INSTRUMENT="FUTSTK") and b.MONTH_CODE="1M" order by TIMESTAMP desc limit 10'

    data = pd.read_sql(sql % (symbol, symbol), db)
    db.close()
    data = data.set_index("TIME")
    data["HIST_VOL"] = pd.rolling_std(data.SETTLE_PR.pct_change(), window=22) * 100 * math.sqrt(252 / 22)
    data.plot(subplots=True)
    plt.show()
