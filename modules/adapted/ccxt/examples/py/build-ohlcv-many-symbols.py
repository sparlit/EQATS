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
import asyncio
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import ccxt.pro

print("CCXT Version:", ccxt.__version__)


async def loop(exchange, symbol, timeframe, complete_candles_only=False):
    duration_in_seconds = exchange.parse_timeframe(timeframe)
    duration_in_ms = duration_in_seconds * 1000
    while True:
        try:
            trades = await exchange.watch_trades(symbol)
            if len(trades) > 0:
                current_minute = int(exchange.milliseconds() / duration_in_ms)
                ohlcvc = exchange.build_ohlcvc(trades, timeframe)
                if complete_candles_only:
                    ohlcvc = [candle for candle in ohlcvc if int(candle[0] / duration_in_ms) < current_minute]
                if len(ohlcvc) > 0:
                    print("-----------------------------------------------------------")
                    print("Symbol:", symbol, "timeframe:", timeframe)
                    print(ohlcvc)

        except Exception as e:
            print(f"{type(e).__name__}: {e!s}")
            # raise type(e)(str(e))  # uncomment to break all loops in case of an error in any one of them
            # break  # you can also break just this one loop if it fails


async def main():
    # select the exchange
    exchange = ccxt.pro.binance()
    if exchange.has["watchTrades"]:
        markets = await exchange.load_markets()
        # Change this value accordingly
        timeframe = "1m"
        limit = 5
        selected_symbols = list(markets.values())[:limit]
        # you can also specify the symbols manually
        # selected_symbols = ['BTC/USDT', 'ETH/USDT']

        # Use this variable to choose if only complete candles
        # should be considered
        complete_candles_only = True
        await asyncio.gather(
            *[loop(exchange, symbol["symbol"], timeframe, complete_candles_only) for symbol in selected_symbols]
        )
        await exchange.close()
    else:
        print(exchange.id, "does not support watchTrades yet")


run(main())
