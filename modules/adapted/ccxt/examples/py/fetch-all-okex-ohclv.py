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
from ccxt.base.exchange import Exchange  # noqa: E402

# An example of OOP / class inheritance in Python


class ohlcv(Exchange):
    def fetch_all_ohlcvs(self, symbol, timeframe, max_retries=3):
        print("Loading", self.id, "markets...")
        self.load_markets()
        print("Loaded", self.id, "markets.")
        limit = 100
        earliest_timestamp = self.milliseconds()
        timeframe_duration_in_seconds = self.parse_timeframe(timeframe)
        timeframe_duration_in_ms = timeframe_duration_in_seconds * 1000
        timedelta = limit * timeframe_duration_in_ms
        ohlcv_dictionary = {}
        ohlcv_list = []
        i = 0
        done = False
        while True:
            # this printout is here for explanation purposes
            print("===========================================================")
            print("Iteration", i)
            fetch_since = earliest_timestamp - timedelta
            print(
                "Fetching",
                self.id,
                symbol,
                timeframe,
                "candles from",
                self.iso8601(fetch_since),
                "to",
                self.iso8601(earliest_timestamp),
            )
            num_retries = 0
            try:
                num_retries += 1
                ohlcv = self.fetch_ohlcv(symbol, timeframe, fetch_since, limit)
                if len(ohlcv):
                    earliest_timestamp = ohlcv[0][0] - timeframe_duration_in_ms
                    print(
                        "Fetched",
                        len(ohlcv),
                        self.id,
                        symbol,
                        timeframe,
                        "candles from",
                        self.iso8601(ohlcv[0][0]),
                        "to",
                        self.iso8601(ohlcv[-1][0]),
                    )
                else:
                    print("Fetched", len(ohlcv), self.id, symbol, timeframe, "candles")
                    done = True
            except Exception:
                if num_retries > max_retries:
                    raise
                continue
            i += 1
            ohlcv_dictionary = self.extend(ohlcv_dictionary, self.indexBy(ohlcv, 0))
            ohlcv_list = self.sort_by(ohlcv_dictionary.values(), 0)
            if len(ohlcv_list):
                print(
                    "Stored",
                    len(ohlcv_list),
                    self.id,
                    symbol,
                    timeframe,
                    "candles from",
                    self.iso8601(ohlcv_list[0][0]),
                    "to",
                    self.iso8601(ohlcv_list[-1][0]),
                )
            if done:
                break
        return ohlcv_list


# Another example of OOP / class inheritance.
# This time my_okx class is inherited from two other classes
# both ohlcv and ccxt.okx, and has the methods from both classes.
# This is just an example, it is not necessary do it this way.
# You can combine classes and methods using Python's OOP how you like.


class my_okx(ohlcv, ccxt.okx):
    pass


# instantiate your class and call the inherited method

exchange = my_okx(
    {
        # 'hostname': 'okx.me',  # if you're in mainland China
    }
)

symbol = "BTC/USDT"
timeframe = "1m"
ohlcvs = exchange.fetch_all_ohlcvs(symbol, timeframe)
print("Done.")
