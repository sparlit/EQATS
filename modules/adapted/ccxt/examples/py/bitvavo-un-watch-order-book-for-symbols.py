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


import asyncio
import os
import sys

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root + "/python")


import ccxt.pro  # noqa: E402


def describe(update):
    # summarize whatever a watch*ForSymbols call returned
    if isinstance(update, dict) and "bids" in update:  # order book
        return update["symbol"] + " bid " + str(update["bids"][0]) + " ask " + str(update["asks"][0])
    if isinstance(update, dict):  # watch_ohlcv_for_symbols -> {symbol: {timeframe: candles}}
        symbol = next(iter(update.keys()))
        timeframe = next(iter(update[symbol].keys()))
        candle = update[symbol][timeframe][-1]
        return symbol + " " + timeframe + " candle " + str(candle)
    trade = update[0]  # trades -> list of trade structures
    return trade["symbol"] + " " + trade["side"] + " " + str(trade["amount"]) + " @ " + str(trade["price"])


async def watch_for(exchange, watch, args, seconds):
    deadline = exchange.milliseconds() + seconds * 1000
    while exchange.milliseconds() < deadline:
        update = await watch(*args)
        print(exchange.iso8601(exchange.milliseconds()), describe(update))


async def test_cycle(exchange, name, watch, un_watch, args):
    print("\n========== " + name + " ==========")
    # 1. subscribe
    print("--- subscribing ---")
    await watch_for(exchange, watch, args, 8)
    # 2. unsubscribe
    print("--- unsubscribing ---")
    await un_watch(*args)
    print("unsubscribed, sleeping 5s (no updates expected)")
    await asyncio.sleep(5)
    # 3. subscribe again
    print("--- subscribing again ---")
    await watch_for(exchange, watch, args, 8)
    print(name + " done")


async def main():
    exchange = ccxt.pro.bitvavo()
    try:
        await exchange.load_markets()
        symbols = ["BTC/EUR", "ETH/EUR"]
        symbols_and_timeframes = [["BTC/EUR", "1m"], ["ETH/EUR", "1m"]]
        await test_cycle(
            exchange,
            "watchOrderBookForSymbols",
            exchange.watch_order_book_for_symbols,
            exchange.un_watch_order_book_for_symbols,
            [symbols],
        )
        await test_cycle(
            exchange,
            "watchTradesForSymbols",
            exchange.watch_trades_for_symbols,
            exchange.un_watch_trades_for_symbols,
            [symbols],
        )
        await test_cycle(
            exchange,
            "watchOHLCVForSymbols",
            exchange.watch_ohlcv_for_symbols,
            exchange.un_watch_ohlcv_for_symbols,
            [symbols_and_timeframes],
        )
        print("\nall done")
    finally:
        await exchange.close()


asyncio.run(main())
