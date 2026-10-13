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


"""Bridges from the shared core to the shapes existing callers already speak.

These exist so a consumer can adopt the core without changing its persistence,
its SocketIO payloads or its tests on the same day. They are still pure.
"""


from collections.abc import Mapping
from typing import Any

from services.risk.models import PositionRisk
from services.risk.position import evaluate_position


def evaluate_trail(state: Mapping[str, Any], last_price: Any) -> dict[str, Any]:
    """Drop in replacement for ``scalping_risk_monitor_service.evaluate_trail``.

    Same input dict, same output keys, same ``sl`` / ``target`` reason strings.
    The differences are the four defects the core fixes, all of which make the
    engine safer rather than more eager: a position with no stop configured no
    longer gets an implicit one at entry, a zero stop or target is read as
    absent, an unusable last price leaves the state alone, and the trail arms
    off the favourable peak so it survives a restart. See the reconciliation
    notes in ``services/risk/position.py``.
    """
    risk = PositionRisk.from_state(state)
    decision = evaluate_position(risk, last_price)
    if not decision.evaluated:
        # The legacy contract has no "not evaluated" state, so report the input
        # unchanged and no breach. The caller's own diff then sees no movement.
        return {
            "highest_price": state.get("highest_price"),
            "lowest_price": state.get("lowest_price"),
            "current_sl": state.get("current_sl"),
            "breached": False,
            "reason": None,
        }
    return decision.to_trail_state()


__all__ = ["evaluate_trail"]
