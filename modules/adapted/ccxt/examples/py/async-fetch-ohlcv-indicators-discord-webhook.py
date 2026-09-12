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


from asyncio import ensure_future, gather
from importlib import import_module
from importlib.util import find_spec

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import ccxt.async_support as ccxt  # noqa: E402
import pandas as pd
import pandas_ta as ta

# -----------------------------------------------------------------------------

print("CCXT Version:", ccxt.__version__)

# -----------------------------------------------------------------------------


async def send_discord_webhook_messsage(exchange, symbol, message):
    payload = {"username": "Kj Bot Top 10 Coins 15 Min TF", "content": message}
    # change your webhook URL here
    url = "https://discord.com/api/webhooks/xxxxxxxxxxxxxxxxxx/xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    method = "POST"
    headers = {"Content-Type": "application/json"}
    body = exchange.json(payload)
    try:
        await exchange.fetch(url, method, headers, body)
    except Exception as e:
        print(type(e).__name__, str(e))


async def run_ohlcv_loop(exchange, symbol, timeframe, limit):
    since = None
    while True:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, since, limit)
            if len(ohlcv):
                df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
                rsi = df.ta.rsi()
                df = pd.concat([df, rsi], axis=1)
                last_row = df.iloc[-1]
                previous_row = df.iloc[-2]
                if last_row["RSI_14"] and previous_row["RSI_14"]:
                    now = exchange.milliseconds()
                    iso8601 = exchange.iso8601(now)
                    print(iso8601, timeframe, symbol, "\tRSI_14 =", last_row["RSI_14"])
                    rsienterob = previous_row["RSI_14"] < 70 and last_row["RSI_14"] > 70
                    if rsienterob:
                        message = iso8601 + " " + timeframe + " " + symbol + " is entering overbought zone"
                        print(message)
                        ensure_future(send_discord_webhook_messsage(exchange, symbol, message))
        except Exception as e:
            print(type(e).__name__, str(e))


async def main():
    exchange = ccxt.binance()
    timeframe = "1m"
    limit = 50
    symbols = ["BTC/USDT", "ETH/USDT"]
    loops = [run_ohlcv_loop(exchange, symbol, timeframe, limit) for symbol in symbols]
    await gather(*loops)
    await exchange.close()


run(main())
