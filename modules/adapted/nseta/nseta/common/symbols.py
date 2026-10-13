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
import io

import pandas as pd
from nseta.common.log import tracelog
from nseta.common.urls import equity_symbol_list_url, index_constituents_url


def get_symbol_list():
    res = equity_symbol_list_url()
    df = pd.read_csv(io.StringIO(res.content.decode("utf-8")))
    return df


@tracelog
def get_index_constituents_list(index):
    res = index_constituents_url(index.lower())
    df = pd.read_csv(io.StringIO(res.content.decode("utf-8")))
    return df
