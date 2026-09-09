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


import signal
import sys
from pathlib import Path
from time import sleep
from typing import Dict, Tuple

from pyalgo import init_logger

from .context import Context


class Engine:
    """"""

    def __init__(self, interval: float, level: str = "info"):
        self.APPNAME = Path(sys.argv[0]).stem
        self.logger = init_logger(level, f"log/{self.APPNAME}")
        self.interval = interval

        self.contexts: dict[tuple[str, int], Context] = {}
        self.active = False

        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)

    def make_session(self, addr: str, session_id: int, name: str, trading: bool = False) -> Context:
        key = (addr, session_id)
        if key in self.contexts:
            return self.contexts[key]

        context = Context(addr, session_id, name, trading)
        self.contexts[key] = context

        context.connect()

        return context

    def run(self):
        self.active = True

        while self.active:
            for context in self.contexts.values():
                context.process()
            sleep(self.interval)

    def stop(self, *_):
        self.active = False
