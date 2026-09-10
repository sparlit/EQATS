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


from datetime import date
from pprint import pprint as print

from RustQuant.data import (
    Curve,
    CurveType,
    InterpolationMethod,
)
from RustQuant.time import (
    Calendar,
    Market,
)

dates = [
    date(2026, 1, 1),
    date(2027, 1, 2),
    date(2028, 1, 3),
    date(2029, 1, 4),
    date(2030, 1, 5),
]
rates = [
    0.01,
    0.015,
    0.012,
    0.014,
    0.013,
]

crv = Curve(dates, rates, CurveType.Spot, InterpolationMethod.Linear)


new_dates = [
    date(2026, 6, 1),
    date(2026, 6, 2),
    date(2026, 6, 3),
    date(2026, 6, 4),
    date(2026, 6, 5),
]

cal = Calendar(Market.Australia)
cal.market()
cal.extra_holidays()
cal.is_business_day(date(2023, 1, 3))
cal.add_holiday(date(2023, 1, 6))
