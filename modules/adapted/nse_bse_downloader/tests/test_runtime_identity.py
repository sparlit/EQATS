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


import sys
from types import SimpleNamespace

import runtime_identity
from app_metadata import PRODUCT_NAME


def test_process_identity_uses_product_name(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "setproctitle",
        SimpleNamespace(setproctitle=calls.append),
    )
    monkeypatch.setattr(runtime_identity.sys, "platform", "linux")

    assert runtime_identity.configure_process_identity()
    assert calls == [PRODUCT_NAME]


def test_process_identity_is_best_effort(monkeypatch):
    monkeypatch.setitem(sys.modules, "setproctitle", None)
    monkeypatch.setattr(runtime_identity.sys, "platform", "linux")

    assert not runtime_identity.configure_process_identity()
