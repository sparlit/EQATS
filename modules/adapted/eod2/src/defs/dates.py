from __future__ import annotations

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


import logging
from datetime import datetime, timedelta

import tzlocal

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

TZ_IN = ZoneInfo("Asia/Kolkata")
TZ_LOCAL = tzlocal.get_localzone()


class Dates:
    """A class for date related functions in EOD2"""

    def __init__(self, last_update: str):
        today = datetime.now(TZ_IN)

        self.today = datetime.combine(today, datetime.min.time())

        dt = datetime.fromisoformat(last_update).astimezone(TZ_IN)

        self.dt = self.lastUpdate = dt

        self.pandas_dt = self.dt.strftime("%Y-%m-%d")

    def nextDate(self):
        """Set the next trading date and return True.
        If its a future date, return False
        """
        cur_time = datetime.now(TZ_IN)
        self.dt = self.dt + timedelta(1)

        if self.dt > cur_time:
            logger.info("All Up To Date")
            return False

        if self.dt.day == cur_time.day and cur_time.hour < 16:
            # Display the users local time
            local_time = cur_time.replace(hour=19, minute=0).astimezone(TZ_LOCAL)

            t_str = local_time.strftime("%I:%M%p")  # 07:00PM

            logger.info(f"All Up To Date. Check again after {t_str} for today's EOD data")
            return False

        self.pandas_dt = self.dt.strftime("%Y-%m-%d")
        return True
