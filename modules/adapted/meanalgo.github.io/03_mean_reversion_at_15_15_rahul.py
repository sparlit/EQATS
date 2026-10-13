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


import datetime
import logging

import pandas as pd
import yaml
from api_helper import ShoonyaApiPy

# enable dbug to see request and responses
logging.basicConfig(level=logging.DEBUG)

# start of our program
shoonya = ShoonyaApiPy()
pd.set_option("display.width", 1000)

# credentials
# yaml for parameters
with open("cred_rahul.yml") as f:
    cred = yaml.load(f, Loader=yaml.FullLoader)
    print(cred)

ret = shoonya.login(
    userid=cred["user"],
    password=cred["pwd"],
    twoFA=cred["factor2"],
    vendor_code=cred["vc"],
    api_secret=cred["apikey"],
    imei=cred["imei"],
)


def exit_all_intraday_positions():
    a = shoonya.get_positions()
    a = pd.DataFrame(a)
    # a.to_csv('positions.csv')
    # print(a.iloc[-1])
    print(a)
    if a.empty:
        print("no positions found, returning empty")
        return
    print(a[["tsym", "exch", "prd", "netqty", "token", "lp", "urmtom", "rpnl", "actid"]])
    print(f"realized profit :: {a['rpnl'].astype(float).sum().round(2)}")
    print(f"unrealized mtm :: {a['urmtom'].astype(float).sum().round(2)}")

    for i in a.itertuples():
        if i.prd == "I":
            qty = int(i.netqty)
            if qty < 0:
                shoonya.place_order(
                    buy_or_sell="B",
                    product_type="I",
                    exchange="NSE",
                    tradingsymbol=i.tysm,
                    quantity=qty,
                    discloseqty=0,
                    price_type="MKT",
                    price=0,
                    remarks="exit_at_15_15_buy",
                )
                print(f"exit order placed in {i.tsym}")
            elif qty > 0:
                shoonya.place_order(
                    buy_or_sell="S",
                    product_type="I",
                    exchange="NSE",
                    tradingsymbol=i.tysm,
                    quantity=qty,
                    price_type="MKT",
                    remarks="exit_at_15_15_sell",
                )
                print(f"exit order placed in {i.tsym}")
            else:
                print(f"net quantity is not less than zero for {i.tsym} => {qty}")


if __name__ == "__main__":
    exit_all_intraday_positions()
