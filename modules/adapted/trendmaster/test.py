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


import traceback

import torch
from trendmaster.trendmaster import PositionalEncoding, TransAm

import __main__

__main__.TransAm = TransAm
__main__.PositionalEncoding = PositionalEncoding

try:
    torch.load("c:/Users/nitya/Desktop/18/Inference/best_model_multi10.pt", map_location="cpu", weights_only=False)
    print("Loaded successfully")
except Exception:
    with open("error.txt", "w") as f:
        f.write(traceback.format_exc())
