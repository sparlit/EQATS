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

print("CCXT Version:", ccxt.__version__)

exchange = ccxt.binanceusdm(
    {
        "apiKey": "YOUR_API_KEY",
        "secret": "YOUR_API_SECRET",
    }
)

print("Loading markets from", exchange.id)
exchange.load_markets()
print("Loaded markets from", exchange.id)

exchange.verbose = True

symbol = "ETH/USDT"
type = "market"
side = "buy"  # long
amount = 10

order1 = exchange.create_order(symbol, "market", "buy", amount)

order1_price = order1["price"]
if order1_price is None:
    order1_price = order1["average"]
if order1_price is None:
    cumulative_quote = float(order1["info"]["cumQuote"])
    executed_quantity = float(order1["info"]["executedQty"])
    order1_price = cumulative_quote / executed_quantity


print("---------------------------------------------------------------------")

stop_loss_params = {"stopPrice": order1_price * 0.9}
order2 = exchange.create_order(symbol, "stop_market", "sell", amount, None, stop_loss_params)

print("---------------------------------------------------------------------")

take_profit_params = {"stopPrice": order1_price * 1.6}
order3 = exchange.create_order(symbol, "take_profit_market", "sell", amount, None, take_profit_params)
