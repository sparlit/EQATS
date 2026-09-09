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


# -*- coding: utf-8 -*-

import os
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402


def style(s, style):
    return style + s + "\033[0m"


def green(s):
    return style(s, "\033[92m")


def blue(s):
    return style(s, "\033[94m")


def yellow(s):
    return style(s, "\033[93m")


def red(s):
    return style(s, "\033[91m")


def pink(s):
    return style(s, "\033[95m")


def bold(s):
    return style(s, "\033[1m")


def underline(s):
    return style(s, "\033[4m")


def dump(*args):
    print(" ".join([str(arg) for arg in args]))


def print_supported_exchanges():
    dump("Supported exchanges:", green(", ".join(ccxt.exchanges)))


try:
    id = sys.argv[1]  # get exchange id from command line arguments

    # check if the exchange is supported by ccxt
    exchange_found = id in ccxt.exchanges

    if exchange_found:
        dump("Instantiating", green(id), "exchange")

        # instantiate the exchange by id
        exchange = getattr(ccxt, id)(
            {
                # 'proxy':'https://cors-anywhere.herokuapp.com/',
            }
        )

        # load all markets from the exchange
        markets = exchange.load_markets()

        # output a list of all market symbols
        dump(green(id), "has", len(exchange.symbols), "symbols:", exchange.symbols)

        tuples = list(ccxt.Exchange.keysort(markets).items())

        # debug
        for _k, v in tuples:
            print(v)

        # output a table of all markets
        dump(pink("{:<15} {:<15} {:<15} {:<15}".format("id", "symbol", "base", "quote")))

        for _k, v in tuples:
            dump("{:<15} {:<15} {:<15} {:<15}".format(v["id"], v["symbol"], v["base"], v["quote"]))

    else:
        dump("Exchange " + red(id) + " not found")
        print_supported_exchanges()

except Exception as e:
    dump("[" + type(e).__name__ + "]", str(e))
    dump("Usage: python " + sys.argv[0], green("id"))
    print_supported_exchanges()
