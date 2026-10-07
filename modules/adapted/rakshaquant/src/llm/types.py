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


"""Shared LLM types (plan M6): usage, a client's reply, and the failures the router acts on."""


from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reported_cost_usd: Decimal | None = None  # e.g. OpenRouter's usage.cost


@dataclass(frozen=True)
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ClientReply:
    """A schema-validated reply from one provider call."""

    parsed: BaseModel
    usage: Usage
    raw_text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


class LLMError(Exception):
    """Base of the failures the router falls back on."""

    outcome = "error"


class LLMTimeoutError(LLMError):
    outcome = "timeout"


class LLMRateLimitedError(LLMError):
    outcome = "rate_limited"

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMServerError(LLMError):
    outcome = "server_error"


class LLMInvalidOutputError(LLMError):
    """The reply did not parse into the schema."""

    outcome = "invalid_output"


class LLMRefusalError(LLMError):
    """The model refused; the caller's answer becomes ABSTAIN."""

    outcome = "refusal"


class BudgetExceededError(LLMError):
    outcome = "budget_exceeded"
