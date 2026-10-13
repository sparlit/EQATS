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


#!/usr/bin/env python3
"""
Entry point shim: `python main.py` continues to work after the restructure.

The runtime moved to src/shortcircuit/runtime/supervisor.py. This file is kept
deliberately — the bot is launched by hand and by any existing service
definition as `python main.py`, and silently changing that command is exactly
the kind of breakage a repackaging exercise is supposed to avoid.

Equivalent, once the package is installed:  python -m shortcircuit
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from shortcircuit.runtime.supervisor import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
