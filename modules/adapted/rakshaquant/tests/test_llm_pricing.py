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


"""Plan M6: LLM pricing - USD per 1M tokens per provider:model, free models, INR."""


from decimal import Decimal

from src.llm.pricing import PricingTable, to_inr
from src.llm.registry import ModelSpec
from src.llm.types import Usage

TABLE = PricingTable.from_yaml()
M = ModelSpec.parse


def test_the_planned_anthropic_rates_and_dated_ids():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert TABLE.cost_usd(M("anthropic:claude-opus-5-5"), usage) == Decimal("24")
    assert TABLE.cost_usd(M("anthropic:claude-sonnet-5-5"), usage) == Decimal("12")
    assert TABLE.cost_usd(M("anthropic:claude-haiku-4-5-20251001"), usage) == Decimal("6")


def test_cache_tokens_are_priced_relative_to_input():
    usage = Usage(cache_read_tokens=1_000_000, cache_write_tokens=1_000_000)
    assert TABLE.cost_usd(M("anthropic:claude-sonnet-5-5"), usage) == Decimal("2.7")  # 0.2 + 2.5


def test_groq_free_and_local_models():
    usage = Usage(input_tokens=2_000, output_tokens=500)
    assert TABLE.cost_usd(M("groq:llama-3.3-70b-versatile"), usage) == Decimal("0.001575")
    assert TABLE.cost_usd(M("openrouter:meta-llama/llama-3.3-70b-instruct:free"), usage) == 0
    assert TABLE.cost_usd(M("ollama:llama3.2"), usage) == 0


def test_a_reported_cost_wins_and_unknown_models_are_flagged_not_zero():
    reported = Usage(input_tokens=10, reported_cost_usd=Decimal("0.0042"))
    assert TABLE.cost_usd(M("openrouter:some/paid-model"), reported) == Decimal("0.0042")
    assert TABLE.cost_usd(M("openrouter:some/paid-model"), Usage(input_tokens=10)) is None
    assert TABLE.price(M("openai:gpt-unknown")) is None


def test_inr():
    assert to_inr(Decimal("0.5"), 88.0) == Decimal("44.0000")
    assert to_inr(None, 88.0) is None
