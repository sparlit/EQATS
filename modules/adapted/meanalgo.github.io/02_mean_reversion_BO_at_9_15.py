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
from datetime import datetime as dt

import pandas as pd
import yaml
from api_helper import ShoonyaApiPy

# enable debug to see request and responses
logging.basicConfig(level=logging.DEBUG, filename=__file__ + ".log")

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


def place_bracket_orders():
    # print('place Limit orders time :: ', dt.now(tz=zone))
    t = dt.today()
    df = pd.read_csv(t.strftime("data/mean_reversion.csv", index_col=None))

    for stock in df.itertuples():
        print(stock.nsecode, stock.qty, stock.trigger_price, stock.target, stock.stoploss)
        shoonya.place_order(
            buy_or_sell="S",
            product_type="B",
            exchange="NSE",
            tradingsymbol=f"{stock.nsecode}-EQ",
            quantity=stock.qty,
            discloseqty=0,
            price_type="LMT",
            price=stock.trigger_price - 0.1,
            trigger_price=stock.trigger_price,
            retention="DAY",
            remarks="entry_at_09_15",
            bookloss_price=stock.stoploss,
            bookprofit_price=stock.target,
        )


if __name__ == "__main__":
    place_bracket_orders()
    shoonya.logout()
