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


"""Event-calendar checks (plan M7.8; audit §J.2): entries are blocked in windows built by
:mod:`src.risk.events` from classified announcements. They never apply to exits."""


from collections.abc import Callable

from src.domain.types import ReasonCode, RiskCheckResult
from src.risk.checks.base import OPENS, Check, block
from src.risk.snapshot import RiskContext
from src.utils.market_time import IST

R = ReasonCode


def _window(code: ReasonCode) -> Callable[[RiskContext], RiskCheckResult | None]:
    def check(ctx: RiskContext) -> RiskCheckResult | None:
        today = ctx.snapshot.now.astimezone(IST).date()
        for b in ctx.snapshot.event_blocks.get(ctx.instrument.key, ()):
            if b.code is code and b.covers(today):
                return block(code, f"{b.reason} (blocked {b.start} to {b.end})",
                             observed=b.event_id, limit=f"{b.start}..{b.end}")  # fmt: skip
        return None

    return check


CHECKS = (
    Check(R.EVT_RESULTS_WINDOW, OPENS, _window(R.EVT_RESULTS_WINDOW)),
    Check(R.EVT_ADVERSE_MAJOR, OPENS, _window(R.EVT_ADVERSE_MAJOR)),
)
