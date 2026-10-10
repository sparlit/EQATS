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


## WebSocket
from smartapi import WebSocket

FEED_TOKEN = "your feed token"

# fetch the feedtoken
feedToken = obj.getfeedToken()
FEED_TOKEN = feedToken

CLIENT_CODE = "your client Id"
token = "channel you want the information of"  # "nse_cm|2885&nse_cm|1594&nse_cm|11536"

ss = WebSocket(FEED_TOKEN, CLIENT_CODE)


def on_tick(ws, tick):
    print(f"Ticks: {tick}")


def on_connect(ws, response):
    ws.send_request(token)


def on_close(ws, code, reason):
    ws.stop()


# Assign the callbacks.
ss.on_ticks = on_tick
ss.on_connect = on_connect
ss.on_close = on_close

ss.connect()
