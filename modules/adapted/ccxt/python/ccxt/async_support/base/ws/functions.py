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

from gzip import GzipFile
from io import BytesIO
from zlib import MAX_WBITS, decompress


def inflate(data):
    return decompress(data, -MAX_WBITS)


def gunzip(data):
    return GzipFile("", "rb", 9, BytesIO(data)).read().decode("utf-8")


def is_json_encoded_object(input):
    # deliberately NOT Exchange.is_json_encoded_object: the ws client feeds the
    # result straight into json.loads with no try/except, so a lone '{' or '['
    # frame must stay a plain string here (the base helper has no length guard)
    return isinstance(input, str) and (len(input) >= 2) and ((input[0] == "{") or (input[0] == "["))
