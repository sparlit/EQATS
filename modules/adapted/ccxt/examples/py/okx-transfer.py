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


from pprint import pprint

import ccxt

# make sure your version is the latest
print("CCXT Version:", ccxt.__version__)

exchange = ccxt.okx(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
        "password": "YOUR_API_PASSWORD",
    }
)

exchange.load_markets()

# https://github.com/ccxt/ccxt/wiki/Manual#implicit-api-methods
# https://github.com/ccxt/ccxt/wiki/Manual#passing-parameters-to-api-methods
# uncomment to see all available methods
# pprint(dir(exchange))

code = "BTC"
currency = exchange.currency(code)


try:
    response = exchange.account_post_transfer(
        {
            "currency": currency["id"],
            "amount": "0.1",
            # 'type': '0',  # 0 transfer between accounts, 1 main to sub_account, 2 sub_account to main
            "from": "6",  # 1 spot, 3 futures, 5 margin, 6 funding account, 9 swap, 12 option
            "to": "1",  # 1 spot, 3 futures, 5 margin, 6 funding account, 9 swap, 12 option
            # 'sub_account': 'name_of_sub_account',  # when type is 1 or 2 sub_account is required
            # 'instrument_id': 'String',  # margin trading pair of token or underlying of USDT-margined futures transferred out, such as: btc-usdt. Limited to trading pairs available for margin trading or underlying of enabled futures trading.
            # 'to_instrument_id': 'String'  # margin trading pair of token or underlying of USDT-margined futures transferred in, such as: btc-usdt. Limited to trading pairs available for margin trading or underlying of enabled futures trading.
        }
    )
except Exception as e:
    print(type(e).__name__, str(e))
