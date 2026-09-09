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


from importlib import import_module
from importlib.util import find_spec

import ccxt.pro

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run

print("CCXT Pro version", ccxt.pro.__version__)


def table(values):
    first = values[0]
    keys = list(first.keys()) if isinstance(first, dict) else range(len(first))
    widths = [max([len(str(v[k])) for v in values]) for k in keys]
    string = " | ".join(["{:<" + str(w) + "}" for w in widths])
    return "\n".join([string.format(*[str(v[k]) for k in keys]) for v in values])


async def main():
    exchange = ccxt.pro.binance(
        {
            # 'options': {
            #     'OHLCVLimit': 1000, # how many candles to store in memory by default
            # },
        }
    )
    symbol = "ETH/USDT"  # or BNB/USDT, etc...
    timeframe = "1m"  # 5m, 1h, 1d
    limit = 10  # how many candles to return max
    method = "watchOHLCV"
    if exchange.has.get(method):
        max_iterations = 100000  # how many times to repeat the loop before exiting
        for i in range(max_iterations):
            try:
                ohlcvs = await exchange.watch_ohlcv(symbol, timeframe, None, limit)
                now = exchange.milliseconds()
                print("\n===============================================================================")
                print("Loop iteration:", i, "current time:", exchange.iso8601(now), symbol, timeframe)
                print("-------------------------------------------------------------------------------")
                print(table([[exchange.iso8601(o[0]), *o[1:]] for o in ohlcvs]))
            except Exception as e:
                print(type(e).__name__, str(e))
                break
        await exchange.close()
    else:
        print(exchange.id, method, "is not supported or not implemented yet")


run(main())
