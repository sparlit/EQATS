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


from asyncio import gather
from importlib import import_module
from importlib.util import find_spec

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run


def table(values):
    first = values[0]
    keys = list(first.keys()) if isinstance(first, dict) else range(len(first))
    widths = [max([len(str(v[k])) for v in values]) for k in keys]
    string = " | ".join(["{:<" + str(w) + "}" for w in widths])
    return "\n".join([string.format(*[str(v[k]) for k in keys]) for v in values])


async def watch_ticker(color, duration, exchange, symbol):
    method = "watchTicker"
    if exchange.has.get(method):
        start = exchange.milliseconds()
        i = 1
        while True:
            ticker = await exchange.watch_ticker(symbol)
            now = exchange.milliseconds()
            # start color code
            print(color, "Ticker ========================================================================")
            print(exchange.iso8601(now), symbol, "iteration:", i, "last price:", ticker["last"])
            print("-------------------------------------------------------------------------------")
            # pprint.pprint(ticker)  # uncomment for a lengthy complete printout
            print("\x1b[0m")  # stop color code
            i += 1
            if (start + duration) < now:
                break
    else:
        raise Exception(exchange.id + " " + method + " is not supported or not implemented yet")


async def watch_ohlcv(color, duration, exchange, symbol, timeframe, limit):
    method = "watchOHLCV"
    if exchange.has.get(method):
        start = exchange.milliseconds()
        i = 1
        while True:
            ohlcvs = await exchange.watch_ohlcv(symbol, timeframe, None, limit)
            now = exchange.milliseconds()
            # start color code
            print(color, "OHLCV =========================================================================")
            print(exchange.iso8601(now), symbol, timeframe, "iteration:", i)
            print("-------------------------------------------------------------------------------")
            print(table([[exchange.iso8601(o[0]), *o[1:]] for o in ohlcvs]))
            print("\x1b[0m")  # stop color code
            i += 1
            if (start + duration) < now:
                break
    else:
        raise Exception(exchange.id + " " + method + " is not supported or not implemented yet")


# =============================================================================


async def main():
    exchange = ccxt.pro.bitmex()
    await exchange.load_markets()
    duration = 1200000  # run 20 minutes = 1200000 milliseconds
    symbol = "BTC/USD"
    limit = 10
    loops = [
        watch_ticker("\033[35m", duration, exchange, symbol),  # magenta
        watch_ohlcv("\x1b[33m", duration, exchange, symbol, "1m", limit),  # yellow
        watch_ohlcv("\x1b[32m", duration, exchange, symbol, "5m", limit),  # green
    ]
    await gather(*loops)
    await exchange.close()


run(main())
