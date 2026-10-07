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


"""Building the LLM router from the settings (plan M6): roles validated at startup (a bad enabled
role is a ``ConfigError`` → exit 2), today's spend rebuilt from the store, the reply cache in the
store."""


from typing import Any

from src.domain.clock import Clock, now_ist
from src.domain.sink import EventSink
from src.llm.clients import ClientFactory
from src.llm.pricing import PricingTable
from src.llm.registry import validate_roles
from src.llm.router import (
    BudgetLimits,
    ClientSource,
    LLMRouter,
    SpendLedger,
    StoreResponseCache,
)
from src.store.event_store import EventStore


def build_router(
    settings: Any,
    *,
    clock: Clock,
    sink: EventSink,
    store: EventStore | None = None,
    clients: ClientSource | None = None,
    use_cache: bool = True,
) -> LLMRouter:
    roles = validate_roles(settings)
    today = now_ist(clock).date()
    ledger = (
        SpendLedger.from_events(store.read(types=["LLMCall"], ist_date=today), today)
        if store is not None
        else None
    )
    cache = (
        StoreResponseCache(store)
        if store is not None and use_cache and settings.llm_cache_enabled
        else None
    )
    return LLMRouter(
        roles=roles,
        clients=clients or ClientFactory(settings),
        pricing=PricingTable.from_yaml(),
        sink=sink,
        clock=clock,
        usd_inr=float(settings.usd_inr),
        timeout_s=float(settings.llm_timeout_s),
        budgets=BudgetLimits.from_settings(settings),
        ledger=ledger,
        cache=cache,
        breaker_failures=int(settings.llm_breaker_failures),
        breaker_cooldown_s=float(settings.llm_breaker_cooldown_s),
    )
