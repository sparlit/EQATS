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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .dtypes import BreadthOption


@dataclass(slots=True)
class NavigationList:
    """Lightweight wrapper to navigate symbols lists"""

    items: list[str] | list[BreadthOption]
    length: int
    current_index: int = 0

    def current(self) -> str:
        """Return the current item."""
        return self.items[self.current_index]

    def next(self) -> str:
        """Move cursor forward, return new current item."""
        if self.can_go_next():
            self.current_index += 1
        return self.current()

    def previous(self) -> str:
        """Move cursor backward, return new current item."""
        if self.can_go_previous():
            self.current_index -= 1
        return self.current()

    def jump_to(self, index: int) -> bool:
        """
        Jump to the given 1-based index and return True on success

        Returns False if index is out of bounds
        """
        if not 1 <= index <= self.length:
            return False

        self.current_index = index - 1
        return True

    def can_go_next(self) -> bool:
        """Check if there is a next item."""
        return self.current_index < self.length - 1

    def can_go_previous(self) -> bool:
        """Check if there is a previous item."""
        return self.current_index > 0
