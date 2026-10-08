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


"""Messaging and host findings from the gthread review.

hosts-messaging-03. Under gthread the remote MCP server points every tool's
SDK client at this process, so a tool never waits for a second request thread
to serve its call back into /api/v1/. check_holiday opened a private HTTP
client instead and made a real loopback call, which with the request pool
nearly full waited 30 seconds for a thread and then failed. It now goes
through the SDK's own client, which is still the HTTP loopback everywhere
else.
"""


import json
import os
import types

import httpx

os.environ.setdefault("OPENALGO_MCP_HTTP_BOOT", "1")

# Importing it pins the installed openalgo SDK over the repo folder of the same
# name, which mcp/mcpserver.py would otherwise import instead.
import test_mcp_integrity  # noqa: E402, F401
from utils.mcp_tool_registry import _load_mcpserver_module  # noqa: E402


def test_check_holiday_goes_through_the_sdks_client(monkeypatch):
    server = _load_mcpserver_module()
    assert server is not None, "could not load mcp/mcpserver.py"
    seen = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200,
            json={"status": "success", "data": {"date": "2026-01-26", "is_holiday": True}},
        )

    sdk = types.SimpleNamespace(client=httpx.Client(transport=httpx.MockTransport(answer)))
    monkeypatch.setattr(server, "client", sdk)
    # Port 9 on loopback answers nothing: a private client would fail here.
    monkeypatch.setattr(server, "host", "http://127.0.0.1:9")
    monkeypatch.setattr(server, "api_key", "the-key")

    # The tool's answer, inside the envelope every MCP tool output carries.
    result = json.loads(server.check_holiday("2026-01-26", "nse"))["data"]

    assert result["data"]["is_holiday"] is True, result
    assert seen == [
        ("/api/v1/checkholiday", {"apikey": "the-key", "date": "2026-01-26", "exchange": "NSE"})
    ]


def test_without_an_sdk_http_client_it_still_calls_the_api_itself(monkeypatch):
    server = _load_mcpserver_module()
    posted = []

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, headers=None):
            posted.append((url, json))
            return types.SimpleNamespace(json=lambda: {"status": "success", "data": {}})

    monkeypatch.setattr(server, "client", None)
    monkeypatch.setattr(server, "host", "http://127.0.0.1:5000")
    monkeypatch.setattr(server, "api_key", "k")
    monkeypatch.setattr(server.httpx, "Client", FakeClient)

    assert json.loads(server.check_holiday("2026-01-27"))["data"]["status"] == "success"
    assert posted == [
        ("http://127.0.0.1:5000/api/v1/checkholiday", {"apikey": "k", "date": "2026-01-27"})
    ]
