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


import multiprocessing as mp
import os
import webbrowser

from . import tempserver as ts


def auth_upstox() -> str:
    """Helps in authorizing Upstox user and returns the access_token.

    Returns
    -------
    str
        Returns the access token for the verified individual.

    """

    def start_server(queue):
        ts.app.queue = queue
        ts.app.run()

    queue = mp.Queue()
    p = mp.Process(target=start_server, args=(queue,))
    print("Starting process. Opening Authentication page...")
    webbrowser.open_new(os.getenv("TEMP_SERVER_AUTH_PAGE"))
    p.start()
    p.join()
    access_token = queue.get()
    print(f"Access Token : {access_token}")
    return access_token
