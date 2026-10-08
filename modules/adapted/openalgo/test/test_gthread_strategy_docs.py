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


"""The threading notes in the trading code describe both runtimes.

These notes are what a maintainer reads before adding a lock, and several
justified their choice by saying every caller is a greenlet. Under the gthread
worker the same locks are real and their callers run in parallel, so advice
that holding one across I/O is harmless, or that a caller cannot be preempted,
becomes wrong. Each module here that talks about greenlets must also say what
happens under gthread, and the sentences that stated eventlet as the only
runtime must not come back.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

MODULES = [
    "services/strategy_module/state.py",
    "services/strategy_module/tick_feed.py",
    "services/strategy_module/broadcast.py",
    "services/strategy_module/checkpoint.py",
    "services/strategy_module/scheduler.py",
    "services/strategy_module/webhook.py",
    "services/strategy_module/engine.py",
    "services/scalping_risk_monitor_service.py",
    "services/websocket_client.py",
    "services/agent/tools/base.py",
    "services/agent/tools/orders.py",
    "sandbox/execution_engine.py",
    "sandbox/websocket_execution_engine.py",
]

#: Sentences that stated eventlet as the only runtime, or were simply wrong.
RETIRED = [
    "Everything that touches this module runs as a greenlet",
    "Every caller of this module is a greenlet",
    "single atomic operation, and every caller is a greenlet",
    "The loop is green.",
    "greenlet holding a lock cannot yield",
    "a greenlet waiting on the lock cannot yield",
    "which is safe from either world",
    "_on_tick() and _on_auth() are invoked on the",
    "socketio.start_background_task`` rather",
    "takes it on the websocket client's asyncio loop thread",
]


def _source(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", MODULES)
def test_a_module_that_talks_about_greenlets_also_names_gthread(rel):
    text = _source(rel)
    if "greenlet" not in text.lower():
        pytest.skip("no threading note about greenlets")
    assert "gthread" in text, f"{rel} explains its locking for eventlet only"


@pytest.mark.parametrize("rel", ["sandbox/execution_engine.py"])
def test_a_module_that_talks_about_the_eventlet_hub_also_names_gthread(rel):
    text = _source(rel)
    assert "eventlet" in text
    assert "gthread" in text, f"{rel} explains its yielding for eventlet only"


@pytest.mark.parametrize("rel", MODULES)
def test_no_retired_sentence_remains(rel):
    text = " ".join(_source(rel).split())
    for sentence in RETIRED:
        assert " ".join(sentence.split()) not in text, f"{rel}: {sentence!r}"
