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


"""
Tests for multi-session chat (#110).

Verifies that different session_ids get independent TradingAgent instances
and that resetting one session doesn't affect another.
"""


import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ["DEPLOY_MODE"] = "self-hosted"
    os.environ["AUTH_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
    with (
        patch("config.credentials.load_all", return_value=None),
        patch("dotenv.load_dotenv", return_value=None),
    ):
        from web.api import app

        yield TestClient(app)


@pytest.fixture(autouse=True)
def clean_sessions():
    """Clear chat sessions between tests."""
    from web.skills import _chat_sessions

    _chat_sessions.clear()
    yield
    _chat_sessions.clear()


def _mock_agent():
    agent = MagicMock()
    agent.chat = MagicMock(return_value="mock response")
    agent._history = [{"role": "user", "content": "test"}]
    return agent


def test_chat_session_id_independent(client):
    """Two different session_ids should get independent TradingAgents."""
    from web.skills import _chat_sessions

    # Pre-populate sessions with mock agents (avoids needing real LLM)
    _chat_sessions["session-a"] = _mock_agent()
    _chat_sessions["session-b"] = _mock_agent()

    resp_a = client.post(
        "/skills/chat",
        json={"message": "hello from A", "session_id": "session-a"},
    )
    assert resp_a.status_code == 200

    resp_b = client.post(
        "/skills/chat",
        json={"message": "hello from B", "session_id": "session-b"},
    )
    assert resp_b.status_code == 200

    # Both sessions exist and are different objects
    assert _chat_sessions["session-a"] is not _chat_sessions["session-b"]

    # Each agent was called with the right message
    _chat_sessions["session-a"].chat.assert_called_with("hello from A")
    _chat_sessions["session-b"].chat.assert_called_with("hello from B")


def test_chat_reset_clears_session(client):
    """Resetting one session should not affect another."""
    from web.skills import _chat_sessions

    _chat_sessions["session-a"] = _mock_agent()
    _chat_sessions["session-b"] = _mock_agent()

    # Reset session A
    resp = client.post("/skills/chat/reset", json={"session_id": "session-a"})
    assert resp.status_code == 200

    # Session A should be gone, session B should remain
    assert "session-a" not in _chat_sessions
    assert "session-b" in _chat_sessions
