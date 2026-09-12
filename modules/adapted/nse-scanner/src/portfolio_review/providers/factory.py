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


"""Environment-driven provider construction."""


import os

from .base import LLMProvider, ProviderError
from .gemini_provider import GeminiProvider
from .groq_provider import GroqProvider


def build_provider(name: str | None = None) -> LLMProvider:
    provider = (name or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
    timeout = int(os.getenv("PORTFOLIO_REVIEW_TIMEOUT_SECONDS", "90"))

    if provider == "gemini":
        return GeminiProvider(
            api_key=os.getenv("GEMINI_API_KEY", ""),
            model=os.getenv("GEMINI_MODEL", os.getenv("LLM_MODEL", "gemini-2.0-flash")),
            timeout=timeout,
        )
    if provider == "groq":
        return GroqProvider(
            api_key=os.getenv("GROQ_API_KEY", ""),
            model=os.getenv("GROQ_MODEL", os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")),
            timeout=timeout,
        )
    msg = f"Unsupported LLM provider: {provider}"
    raise ProviderError(msg)
