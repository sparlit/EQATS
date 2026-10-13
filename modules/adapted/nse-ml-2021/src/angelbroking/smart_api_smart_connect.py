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


# package import statement
from smartapi import SmartConnect  # or from smartapi.smartConnect import SmartConnect

# import smartapi.smartExceptions(for smartExceptions)

# create object of call
obj = SmartConnect(api_key="your api key")

# login api call

data = obj.generateSession("Your Client ID", "Your Password")
refreshToken = data["data"]["refreshToken"]

# fetch the feedtoken
feedToken = obj.getfeedToken()

# fetch User Profile
userProfile = obj.getProfile(refreshToken)
# place order
try:
    orderparams = {
        "variety": "NORMAL",
        "tradingsymbol": "SBIN-EQ",
        "symboltoken": "3045",
        "transactiontype": "BUY",
        "exchange": "NSE",
        "ordertype": "LIMIT",
        "producttype": "INTRADAY",
        "duration": "DAY",
        "price": "19500",
        "squareoff": "0",
        "stoploss": "0",
        "quantity": "1",
    }
    orderId = obj.placeOrder(orderparams)
    print(f"The order id is: {orderId}")
except Exception as e:
    print(f"Order placement failed: {e.message}")

# logout
try:
    logout = obj.terminateSession("Your Client Id")
    print("Logout Successfull")
except Exception as e:
    print(f"Logout failed: {e.message}")
