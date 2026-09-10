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


"""Generate, validate and persist evidence-bound portfolio reviews."""


import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .evidence_collector import collect_evidence
from .prompt_builder import build_review_prompt
from .providers import LLMProvider, ProviderError, build_provider
from .review_repository import ReviewAlreadyExistsError, save_review
from .review_validator import validate_review

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewRunResult:
    symbol: str
    status: str
    provider: str = ""
    model: str = ""
    report_path: str = ""
    error: str = ""


def _provider_order(primary: str | None, fallback: str | None) -> list[str]:
    first = (primary or os.getenv("LLM_PROVIDER", "gemini")).strip().lower()
    second = (fallback or os.getenv("LLM_FALLBACK_PROVIDER", "groq")).strip().lower()
    return list(dict.fromkeys(name for name in (first, second) if name))


def run_review(
    queue_item: dict[str, Any],
    review_period: str,
    *,
    scanner_path: str | Path = "telegram_last_scan.json",
    reports_root: str | Path = "reports/portfolio",
    primary_provider: str | None = None,
    fallback_provider: str | None = None,
    max_retries: int | None = None,
    provider_builder: Callable[[str], LLMProvider] = build_provider,
) -> ReviewRunResult:
    symbol = str(queue_item.get("symbol", "")).strip().upper()
    if not symbol:
        return ReviewRunResult(symbol="", status="FAILED", error="Queue item has no symbol")

    evidence = collect_evidence(queue_item, scanner_path=scanner_path)
    prompt = build_review_prompt(evidence, review_period)
    retries = max_retries if max_retries is not None else int(os.getenv("PORTFOLIO_REVIEW_MAX_RETRIES", "1"))
    delay = float(os.getenv("PORTFOLIO_REVIEW_RETRY_DELAY_SECONDS", "2"))
    errors: list[str] = []

    for provider_name in _provider_order(primary_provider, fallback_provider):
        try:
            provider = provider_builder(provider_name)
        except Exception as exc:
            errors.append(f"{provider_name}: configuration failed: {exc}")
            continue

        for attempt in range(retries + 1):
            try:
                response = provider.generate_review(prompt)
                review = response.payload
                validation_errors = validate_review(review, expected_symbol=symbol)
                if validation_errors:
                    raise ProviderError("; ".join(validation_errors))
                dated_path, _ = save_review(review, reports_root=reports_root)
                return ReviewRunResult(
                    symbol=symbol,
                    status="SUCCESS",
                    provider=response.provider,
                    model=response.model,
                    report_path=str(dated_path),
                )
            except ReviewAlreadyExistsError as exc:
                return ReviewRunResult(symbol=symbol, status="SKIPPED", error=str(exc))
            except Exception as exc:
                errors.append(f"{provider_name} attempt {attempt + 1}: {exc}")
                log.warning("Review generation failed for %s using %s: %s", symbol, provider_name, exc)
                if attempt < retries and delay > 0:
                    time.sleep(delay)

    return ReviewRunResult(symbol=symbol, status="FAILED", error=" | ".join(errors))
