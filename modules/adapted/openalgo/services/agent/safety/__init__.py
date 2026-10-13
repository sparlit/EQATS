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


"""Guardrails for the `/agent` module: the order guard and the audit trail.

Two modules, one job each, and they are deliberately separate:

* :mod:`services.agent.safety.risk` **decides**. It is pure Python, reads its
  limits from the settings store and is handed every market number it needs, so
  nothing the model writes and no broker outage can change its answer.
* :mod:`services.agent.safety.audit` **records**. Every entry point swallows its
  own failures, because losing the paperwork must never stop, or duplicate, a
  trade the operator approved.

Importing this package pulls in neither agno nor a broker. The names below are
re-exported for convenience; `from services.agent.safety import audit` and
`audit.record_attempt(...)` reads better at a call site than a wildcard of the
writer functions, so the audit module itself is exported rather than flattened.
"""

from services.agent.safety import audit
from services.agent.safety.risk import (
    BULK_OPERATIONS,
    KNOWN_OPERATIONS,
    TARGETED_OPERATIONS,
    RiskCode,
    RiskGuard,
    Verdict,
    clear_guards,
    get_guard,
    reset_guard,
)

__all__ = [
    "BULK_OPERATIONS",
    "KNOWN_OPERATIONS",
    "TARGETED_OPERATIONS",
    "RiskCode",
    "RiskGuard",
    "Verdict",
    "audit",
    "clear_guards",
    "get_guard",
    "reset_guard",
]
