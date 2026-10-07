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


from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class AnnouncementAlphaState:
    """Tracks processed announcements to prevent duplicate paper orders."""

    processed_isins: set[str] = field(default_factory=set)
    processed_symbols: set[str] = field(default_factory=set)
    paper_orders_placed: list[dict] = field(default_factory=list)

    def mark_processed(self, symbol: str, isin: str | None = None) -> None:
        self.processed_symbols.add(symbol.upper())
        if isin:
            self.processed_isins.add(isin)

    def is_processed(self, symbol: str, isin: str | None = None) -> bool:
        if symbol.upper() in self.processed_symbols:
            return True
        return bool(isin and isin in self.processed_isins)

    def add_order(self, order: dict) -> None:
        self.paper_orders_placed.append(order)

    def save(self, path: str | None = None) -> None:
        if path:
            import json

            with open(path, "w") as f:
                json.dump(self.__dict__, f, indent=2, default=str)

    def load(self, path: str) -> None:
        import json

        with open(path) as f:
            data = json.load(f)
            self.processed_isins = set(data.get("processed_isins", []))
            self.processed_symbols = set(data.get("processed_symbols", []))
            self.paper_orders_placed = data.get("paper_orders_placed", [])
