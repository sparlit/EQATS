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


import sys
from pprint import pprint

import ccxt

print("python", sys.version)
print("CCXT Version:", ccxt.__version__)

binance = ccxt.binance(
    {
        "apiKey": "YOUR_BINANCE_API_KEY",
        "secret": "YOUR_BINANCE_SECRET",
        "options": {
            "fetchCurrencies": True,
        },
    }
)
binance.verbose = True

kucoin = ccxt.kucoin(
    {
        "apiKey": "YOUR_KUCOIN_API_KEY",
        "secret": "YOUR_KUCOIN_SECRET",
        "password": "YOUR_KUCOIN_API_PASSWORD",
    }
)
kucoin.verbose = True

binance.load_markets()
kucoin.load_markets()

code = "USDT"
amount = 40

params = {"network": "TRC20"}

deposit = binance.fetchDepositAddress(code, params)

print("-----------------------------------------------------------")
print(deposit)
print("-----------------------------------------------------------")

withdrawal = kucoin.withdraw(code, amount, deposit["address"], deposit["tag"], params)

print("-----------------------------------------------------------")
