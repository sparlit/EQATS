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

import yaml
from api_helper import ShoonyaApiPy

logging.basicConfig(level=logging.DEBUG)

# flag to tell us if the websocket is open
socket_opened = False


# application callbacks
def event_handler_order_update(message):
    print("order event: " + str(message))


def event_handler_quote_update(message):
    # e   Exchange
    # tk  Token
    # lp  LTP
    # pc  Percentage change
    # v   volume
    # o   Open price
    # h   High price
    # l   Low price
    # c   Close price
    # ap  Average trade price

    print("quote event: " + str(message))


def open_callback():
    global socket_opened
    socket_opened = True
    print("app is connected")
    # api.subscribe_orders()
    api.subscribe("NSE|22")
    # api.subscribe(['NSE|22', 'BSE|522032'])


# end of callbacks


# start of our program
api = ShoonyaApiPy()

# use following if yaml isnt used
# user    = <uid>
# pwd     = <password>
# factor2 = <2nd factor>
# vc      = <vendor code>
# apikey  = <secret key>
# imei    = <imei>

# ret = api.login(userid = user, password = pwd, twoFA=factor2, vendor_code=vc, api_secret=apikey, imei=imei)

# yaml for parameters
with open("cred.yml") as f:
    cred = yaml.load(f, Loader=yaml.FullLoader)
    print(cred)

ret = api.login(
    userid=cred["user"],
    password=cred["pwd"],
    twoFA=cred["factor2"],
    vendor_code=cred["vc"],
    api_secret=cred["apikey"],
    imei=cred["imei"],
)

if ret is not None:
    while True:
        print("p => place order")
        print("m => modify order")
        print("c => cancel order")
        print("y => order history")
        print("o => get order book")
        print("h => get holdings")
        print("l => get limits")
        print("k => get positions")
        print("d => get daily mtm")
        print("s => start_websocket")
        print("q => quit")

        prompt1 = input("what shall we do? ").lower()

        if prompt1 == "p":
            ret = api.place_order(
                buy_or_sell="B",
                product_type="C",
                exchange="NSE",
                tradingsymbol="INFY-EQ",
                quantity=1,
                discloseqty=0,
                price_type="LMT",
                price=1500.00,
                trigger_price=None,
                retention="DAY",
                remarks="my_order_001",
            )
            print(ret)

        elif prompt1 == "m":
            orderno = input("Enter orderno:").lower()
            ret = api.modify_order(
                exchange="NSE",
                tradingsymbol="INFY-EQ",
                orderno=orderno,
                newquantity=2,
                newprice_type="LMT",
                newprice=1505.00,
            )
            print(ret)

        elif prompt1 == "c":
            orderno = input("Enter orderno:").lower()
            ret = api.cancel_order(orderno=orderno)
            print(ret)

        elif prompt1 == "y":
            orderno = input("Enter orderno:").lower()
            ret = api.single_order_history(orderno=orderno)
            print(ret)

        elif prompt1 == "o":
            ret = api.get_order_book()
            print(ret)

        elif prompt1 == "h":
            ret = api.get_holdings()
            print(ret)

        elif prompt1 == "l":
            ret = api.get_limits()
            print(ret)

        elif prompt1 == "k":
            ret = api.get_positions()
            print(ret)
        elif prompt1 == "d":
            # contributed by Aromal P Nair
            while True:
                ret = api.get_positions()
                mtm = 0
                pnl = 0
                for i in ret:
                    mtm += float(i["urmtom"])
                    pnl += float(i["rpnl"])
                    day_m2m = mtm + pnl
                print(day_m2m)
        elif prompt1 == "s":
            if socket_opened:
                print("websocket already opened")
                continue
            ret = api.start_websocket(
                order_update_callback=event_handler_order_update,
                subscribe_callback=event_handler_quote_update,
                socket_open_callback=open_callback,
            )
            print(ret)
        else:
            print("Fin")  # an answer that wouldn't be yes or no
            break
