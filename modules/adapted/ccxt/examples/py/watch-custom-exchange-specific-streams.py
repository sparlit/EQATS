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

run = import_module(next(filter(find_spec, ("uvloop", "winloop", "asyncio")))).run
import ccxt.pro


class MyBinance(ccxt.pro.binance):
    def handle_mini_ticker(self, client, message):
        market_id = self.safe_string_lower(message, "s")
        message_hash = market_id + "@miniTicker"
        client.resolve(message, message_hash)

    def handle_message(self, client, message):
        handlers = {
            "24hrMiniTicker": self.handle_mini_ticker,
            # add other custom handlers here
        }
        e = self.safe_string(message, "e")
        method = self.safe_value(handlers, e)
        if method:
            return method(client, message)
        return super().handle_message(client, message)


async def main():
    exchange = MyBinance({"enableRateLimit": False, "options": {"defaultType": "future"}})
    await exchange.load_markets()
    # exchange.verbose = True  # uncomment for debugging purposes
    market = exchange.market("BTC/USDT")
    message_hash = market["lowercaseId"] + "@miniTicker"
    while True:
        try:
            print(await exchange.watch_public(message_hash))
        except Exception as e:
            print(type(e).__name__, str(e))
    await exchange.close()


if __name__ == "__main__":
    run(main())
