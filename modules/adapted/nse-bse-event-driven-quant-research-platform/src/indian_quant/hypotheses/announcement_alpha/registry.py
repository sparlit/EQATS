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


"""Announcement Alpha hypothesis — integrates with platform hypothesis registry."""

from indian_quant.hypotheses.base import BaseHypothesis
from indian_quant.hypotheses.registry import register_hypothesis


@register_hypothesis
class AnnouncementAlpha(BaseHypothesis):
    """Buy on BSE announcement signals using paper/sandbox orders."""

    name = "announcement_alpha"
    description = "BSE announcement alpha signals → paper order placement"
    max_positions = 7
    default_stop_pct = 0.05
    default_horizon_days = 5
    price_min = 50.0
    price_max = 5000.0
    min_turnover = 10_000_000.0
    market_cap_min = 500.0
    market_cap_max = 50000.0

    def compute_signals(self, df, *, signal_date=None, announcements=None):
        return []

    def compute_signals_batch(self, frames, *, signal_date=None):
        return []


def register_announcement_alpha() -> None:
    """No-op; @register_hypothesis on the class handles registration."""
    pass


__all__ = ["AnnouncementAlpha", "register_announcement_alpha"]
