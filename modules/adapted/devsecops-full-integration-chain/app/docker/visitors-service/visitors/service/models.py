import datetime
from decimal import ROUND_HALF_UP, Decimal

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    elif dt.tzinfo is None:
        now = ist.localize(dt)
    else:
        now = dt.astimezone(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    tick = Decimal(str(tick_size))
    price_dec = Decimal(str(price))
    rounded = (price_dec / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick
    return float(rounded.quantize(Decimal("0.01")))


try:
    from django.db import models

    class Visitor(models.Model):
        service_ip = models.CharField(max_length=16)
        client_ip = models.CharField(max_length=16)
        timestamp = models.DateTimeField(auto_now_add=True)

        def __str__(self):
            return f"Client IP [{self.client_ip}] Timestamp [{self.timestamp}]"
except ImportError:
    # Django not available - define a placeholder for type checking
    class Visitor:
        service_ip: str
        client_ip: str
        timestamp: datetime.datetime

        def __init__(self, service_ip: str, client_ip: str, timestamp: datetime.datetime):
            self.service_ip = service_ip
            self.client_ip = client_ip
            self.timestamp = timestamp

        def __str__(self):
            return f"Client IP [{self.client_ip}] Timestamp [{self.timestamp}]"
