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

# -----------------------------------------------------------------------------

this_folder = os.path.dirname(os.path.abspath(__file__))
root_folder = os.path.dirname(os.path.dirname(this_folder))
sys.path.append(root_folder + "/python")
sys.path.append(this_folder)

# -----------------------------------------------------------------------------

import ccxt  # noqa: E402

# -----------------------------------------------------------------------------


print("CCXT Version:", ccxt.__version__)


def table(values):
    first = values[0]
    keys = list(first.keys()) if isinstance(first, dict) else range(len(first))
    widths = [max([len(str(v[k])) for v in values]) for k in keys]
    string = " | ".join(["{:<" + str(w) + "}" for w in widths])
    return "\n".join([string.format(*[str(v[k]) for k in keys]) for v in values])


exchange = ccxt.binanceusdm()
try:
    exchange.load_markets()
    timeframe = "1m"
    limit = 1
    symbol = "BTC/USDT"
    market = exchange.market(symbol)
    timeframe = "1m"
    params = {
        "pair": market["id"],
        "contractType": "PERPETUAL",  # 'PERPETUAL', 'CURRENT_MONTH', 'NEXT_MONTH', 'CURRENT_QUARTER', 'NEXT_QUARTER'
        "interval": exchange.timeframes[timeframe],
    }
    # https://binance-docs.github.io/apidocs/futures/en/#continuous-contract-kline-candlestick-data
    ohlcvs = exchange.fapiPublic_get_continuousklines(params)
    print(table(list(ohlcvs)))
    print(table([[exchange.iso8601(int(o[0])), *o[1:]] for o in ohlcvs]))
except Exception as e:
    print(type(e).__name__, str(e))
