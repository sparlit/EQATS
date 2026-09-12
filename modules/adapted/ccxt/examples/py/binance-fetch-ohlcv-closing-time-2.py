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

import asciichart

# -----------------------------------------------------------------------------

this_folder = os.path.dirname(os.path.abspath(__file__))
root_folder = os.path.dirname(os.path.dirname(this_folder))
sys.path.append(root_folder + "/python")
sys.path.append(this_folder)

# -----------------------------------------------------------------------------

import ccxt  # noqa: E402

# -----------------------------------------------------------------------------


class MyBinance(ccxt.binance):
    def parse_ohlcv(self, ohlcv, market=None):
        #
        #     [
        #         1591478520000,
        #         "0.02501300",
        #         "0.02501800",
        #         "0.02500000",
        #         "0.02500000",
        #         "22.19000000",
        #         1591478579999,
        #         "0.55490906",
        #         40,
        #         "10.92900000",
        #         "0.27336462",
        #         "0"
        #     ]
        #
        return [
            self.safe_integer(ohlcv, 6),
            self.safe_number(ohlcv, 1),
            self.safe_number(ohlcv, 2),
            self.safe_number(ohlcv, 3),
            self.safe_number(ohlcv, 4),
            self.safe_number(ohlcv, 5),
        ]


exchange = MyBinance()
symbol = "BTC/USDT"
timeframe = "1h"

ohlcvs = exchange.fetch_ohlcv(symbol, timeframe)
for ohlcv in ohlcvs:
    print([exchange.iso8601(ohlcv[0]), *ohlcv[1:]])
