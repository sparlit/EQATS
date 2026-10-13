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


"""mcp/mcpserver.py is executed once, however many first MCP requests arrive together.

The loaded module was cached on a function attribute with no lock, so two
concurrent first requests (initialize and tools/list) each executed the file,
replacing sys.modules["openalgo_mcp_server"] under the first and building
duplicate SDK clients and tool registrations. Under eventlet the load did not
yield, so they could not overlap.
"""


import contextlib
import threading
import time
import types

import pytest
import utils.mcp_tool_registry as registry


@pytest.fixture
def cold_registry(monkeypatch):
    monkeypatch.delattr(registry._load_mcpserver_module, "_module", raising=False)
    yield registry
    with contextlib.suppress(AttributeError):
        del registry._load_mcpserver_module._module


def test_simultaneous_first_loads_execute_the_file_once(cold_registry, monkeypatch):
    import importlib.util

    executions = []
    real_module_from_spec = importlib.util.module_from_spec

    class SlowLoader:
        def exec_module(self, module):
            executions.append(1)
            time.sleep(0.05)
            module.ACTIVE_TOOL_NAMES = ["get_quote"]

    def fake_spec(name, location):
        return types.SimpleNamespace(loader=SlowLoader(), name=name)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", fake_spec)
    monkeypatch.setattr(
        importlib.util, "module_from_spec", lambda spec: types.ModuleType(spec.name)
    )
    barrier = threading.Barrier(8)
    modules = []

    def first_request():
        barrier.wait()
        modules.append(registry._load_mcpserver_module())

    threads = [threading.Thread(target=first_request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert executions == [1]
    assert len({id(m) for m in modules}) == 1
    assert registry.active_tool_names() == {"get_quote"}
    assert real_module_from_spec is not None
