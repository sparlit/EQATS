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
import time

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")

import ccxt  # noqa: E402


def print_exchanges():
    print("Supported exchanges:", ", ".join(ccxt.exchanges))


def print_usage():
    print("Usage: python", sys.argv[0], "id")
    print("python", sys.argv[0], "kraken")
    print("python", sys.argv[0], "coinbaseexchange")
    print_exchanges()


try:
    id = sys.argv[1]  # get exchange id from command line arguments

    # check if the exchange is supported by ccxt
    exchange_found = id in ccxt.exchanges

    if exchange_found:
        print("Instantiating", id)

        # instantiate the exchange by id
        exchange = getattr(ccxt, id)()

        if not exchange.has["fetchTickers"]:
            raise ccxt.NotSupported(
                "Exchange " + exchange.id + " does not have the endpoint to fetch all tickers from the API."
            )

        # load all markets from the exchange
        markets = exchange.load_markets()

        try:
            tickers = exchange.fetch_tickers()
            for symbol, ticker in tickers.items():
                print(
                    symbol,
                    ticker["datetime"],
                    "high: " + str(ticker["high"]),
                    "low: " + str(ticker["low"]),
                    "bid: " + str(ticker["bid"]),
                    "ask: " + str(ticker["ask"]),
                    "volume: " + str(ticker["quoteVolume"] or ticker["baseVolume"]),
                )

        except ccxt.DDoSProtection as e:
            print(type(e).__name__, e.args, "DDoS Protection (ignoring)")
        except ccxt.RequestTimeout as e:
            print(type(e).__name__, e.args, "Request Timeout (ignoring)")
        except ccxt.ExchangeNotAvailable as e:
            print(type(e).__name__, e.args, "Exchange Not Available due to downtime or maintenance (ignoring)")
        except ccxt.AuthenticationError as e:
            print(type(e).__name__, e.args, "Authentication Error (missing API keys, ignoring)")
    else:
        print("Exchange", id, "not found")
        print_usage()

except Exception as e:
    print(type(e).__name__, e.args, str(e))
    print_usage()
