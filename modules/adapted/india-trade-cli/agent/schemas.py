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
agent/schemas.py
────────────────
Pydantic models for structured LLM outputs.

Scoped to synthesis output only (issue #175).
These are used by agent/schema_parser.py to validate parsed LLM text.
"""


from typing import Literal

from pydantic import BaseModel, Field


class SynthesisOutput(BaseModel):
    """Structured output from the synthesis (fund manager) LLM call."""

    verdict: Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"] = "HOLD"
    confidence: int = Field(default=50, ge=0, le=100)
    winner: Literal["BULL", "BEAR", "NEUTRAL"] = "NEUTRAL"
    strategy: str = ""
    entry: str = ""  # kept as str — may be "at market" or "₹2,850"
    stop_loss: str = ""
    target: str = ""
    risk_reward: str = ""
    position: str = ""
    rationale: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class AnalystSignal(BaseModel):
    """Structured signal from a single analyst."""

    analyst: str
    verdict: Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]
    confidence: int = Field(ge=0, le=100)
    score: float
    key_points: list[str] = Field(default_factory=list)
    error: str = ""


class PersonaSignal(BaseModel):
    """Signal from a named investor persona (Buffett, Jhunjhunwala, etc.)."""

    persona: str
    verdict: Literal["STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"]
    confidence: int = Field(ge=0, le=100)
    rationale: list[str] = Field(default_factory=list)
    key_metrics: dict[str, str] = Field(default_factory=dict)  # metric_name -> value string
