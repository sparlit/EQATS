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


from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AnnouncementCategory(StrEnum):
    ORDER = "Award of Order / Receipt of Order"
    BAGGING = "Bagging/Receiving of orders/contracts"
    RESULTS = "Financial Results"
    BOARD_MEETING = "Board Meeting"
    DIVIDEND = "Dividend"
    PRESS = "Press Release"
    BONUS = "Bonus"
    CAPACITY = "Capacity addition"
    NEW_LISTING = "New Listing"
    PREFERENTIAL = "Preferential Issue"


@dataclass(frozen=True)
class Announcement:
    company: str
    symbol: str
    exchange: str
    category: str
    time: str
    scrip_code: str
    announcement_type: str = ""
    linked_text: str = ""
    published_at: datetime | None = None
    raw: dict | None = None


@dataclass(frozen=True)
class Signal:
    symbol: str
    exchange: str
    scrip_code: str
    category: str
    announcement_type: str
    strength: float
    published_at: datetime | None = None
    notes: str = ""


@dataclass(frozen=True)
class PaperOrderRequest:
    symbol: str
    exchange: str
    instrument_key: str
    quantity: int
    price: float
    tag: str = ""
    product: str = "D"
    validity: str = "DAY"
    order_type: str = "LIMIT"
    disclosed_quantity: int = 0
    trigger_price: float = 0.0
    is_amo: bool = False
    slice: bool = False
