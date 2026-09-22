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
import numpy as np
import pandas as pd

import config

query = (
    'select concat_ws("",a.SYMBOL,cast(a.curyear as char),cast(a.curmonth as char),cast(a.STRIKE as char),cast(a.OPTION_TYP as char)) as CONTRACT from\
        (select SYMBOL,OPTION_TYP,RIGHT(YEAR(EXPIRY_DT),2) as curyear,LEFT(upper(monthname(EXPIRY_DT)),3) as curmonth,if(DELTA>0,min(STRIKE_PR),max(STRIKE_PR))\
        as STRIKE from opt_greeks where TIMESTAMP=(select max(TIMESTAMP) from opt_greeks)\
        and symbol in (select SYMBOL from nsesymbollist) group by SYMBOL,OPTION_TYP) a union\
        select concat(SYMBOL,"-1M") from nsesymbollist'
)
symbolsfile = r"C:/Neotrade/Symbol.txt"


def create_contract_list():
    db = MySQLdb.connect(config.host, config.user, config.password, "NSE")
    stocks = pd.read_sql(query, db)
    stocks.to_csv(symbolsfile, index=False, header=False)
    db.close()


if __name__ == "__main__":
    create_contract_list()
