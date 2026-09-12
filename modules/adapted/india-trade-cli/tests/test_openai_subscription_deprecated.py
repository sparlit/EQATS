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
Tests for OpenAI subscription provider deprecation (#82).
"""


import pytest


class TestOpenAISubscriptionDeprecated:
    def test_instantiation_raises_runtime_error(self, mocker):
        """OpenAISubscriptionProvider must raise immediately — no silent broken usage."""
        from agent.core import OpenAISubscriptionProvider, ToolRegistry

        registry = ToolRegistry()
        with pytest.raises(RuntimeError) as exc_info:
            OpenAISubscriptionProvider("gpt-4o", registry, "You are a trading assistant.")

        err = str(exc_info.value).lower()
        assert "deprecated" in err or "non-functional" in err or "no longer" in err

    def test_error_mentions_openrouter(self, mocker):
        """Error message must provide actionable alternative — OpenRouter."""
        from agent.core import OpenAISubscriptionProvider, ToolRegistry

        registry = ToolRegistry()
        with pytest.raises(RuntimeError) as exc_info:
            OpenAISubscriptionProvider("gpt-4o", registry, "system")

        err = str(exc_info.value).lower()
        assert "openrouter" in err or "open router" in err

    def test_error_mentions_openai_provider(self, mocker):
        """Error must tell user to use AI_PROVIDER=openai instead."""
        from agent.core import OpenAISubscriptionProvider, ToolRegistry

        registry = ToolRegistry()
        with pytest.raises(RuntimeError) as exc_info:
            OpenAISubscriptionProvider("gpt-4o", registry, "system")

        err = str(exc_info.value)
        assert "openai" in err.lower()
