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


def print_exchanges():
    dump("Supported exchanges:", ", ".join(ccxt.exchanges))


def print_usage():
    dump("Usage: python " + sys.argv[0], green("id1"), yellow("id2"), blue("id3"), "...")


proxies = [
    "",  # no proxy by default
    "https://crossorigin.me/",
    "https://cors-anywhere.herokuapp.com/",
]

if len(sys.argv) > 2:
    ids = list(sys.argv[1:])
    exchanges = {}
    dump(ids)
    dump(yellow(" ".join(ids)))
    for id in ids:  # load all markets from all exchange exchanges
        # instantiate the exchange by id
        exchange = getattr(ccxt, id)()

        # save it in a dictionary under its id for future use
        exchanges[id] = exchange

        # load all markets from the exchange
        markets = exchange.load_markets()

        # basic round-robin proxy scheduler
        currentProxy = -1
        maxRetries = len(proxies)

        for _numRetries in range(maxRetries):
            # try proxies in round-robin fashion
            currentProxy = (currentProxy + 1) % len(proxies)

            try:  # try to load exchange markets using current proxy
                exchange.proxy = proxies[currentProxy]
                exchange.load_markets()

            except ccxt.DDoSProtection as e:
                dump(yellow(type(e).__name__), e.args)
            except ccxt.RequestTimeout as e:
                dump(yellow(type(e).__name__), e.args)
            except ccxt.AuthenticationError as e:
                dump(yellow(type(e).__name__), e.args)
            except ccxt.ExchangeNotAvailable as e:
                dump(yellow(type(e).__name__), e.args)
            except ccxt.ExchangeError as e:
                dump(yellow(type(e).__name__), e.args)
            except ccxt.NetworkError as e:
                dump(yellow(type(e).__name__), e.args)
            except Exception:  # reraise all other exceptions
                raise

        dump(green(id), "loaded", green(str(len(exchange.symbols))), "markets")

    dump(green("Loaded all markets"))

    allSymbols = [symbol for id in ids for symbol in exchanges[id].symbols]

    # get all unique symbols
    uniqueSymbols = list(set(allSymbols))

    # filter out symbols that are not present on at least two exchanges
    arbitrableSymbols = sorted([symbol for symbol in uniqueSymbols if allSymbols.count(symbol) > 1])

    # print a table of arbitrable symbols
    table = []
    dump(green(" symbol          | " + "".join([f" {id:<15} | " for id in ids])))
    dump(green("".join(["-----------------+-" for x in range(len(ids) + 1)])))

    for symbol in arbitrableSymbols:
        string = f" {symbol:<15} | "
        row = {}
        for id in ids:
            # if a symbol is present on a exchange print that exchange's id in the row
            string += " {:<15} | ".format(id if symbol in exchanges[id].symbols else "")
        dump(string)

else:
    print_usage()
