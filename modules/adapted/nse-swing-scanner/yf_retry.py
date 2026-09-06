"""
yf_retry.py
Shared retry helper for yfinance / HTTP rate-limit failures on shared
GitHub Actions egress IPs. Import-safe (no yfinance at import time).
"""
from __future__ import annotations

import random
import time
from typing import Callable, Optional, Sequence, TypeVar

T = TypeVar("T")

# Substrings that indicate a transient rate-limit / throttle response.
_RATE_LIMIT_MARKERS = (
    "too many requests",
    "rate limit",
    "rate limited",
    "429",
    "try after a while",
    "temporarily blocked",
)


def is_rate_limit_error(err: object) -> bool:
    """True when `err` (exception or message string) looks like a 429/throttle."""
    if err is None:
        return False
    text = str(err).lower()
    return any(m in text for m in _RATE_LIMIT_MARKERS)


def is_rate_limit_payload(payload: object) -> bool:
    """True when a compute_* dict carries a rate-limit error string."""
    if not isinstance(payload, dict):
        return False
    return is_rate_limit_error(payload.get("error"))


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 2.0,
    jitter_s: float = 0.5,
    is_retryable: Optional[Callable[[BaseException], bool]] = None,
    retryable_result: Optional[Callable[[T], bool]] = None,
) -> T:
    """
    Call `fn()` up to max_attempts times.

    Retries when:
      - fn raises and is_retryable(exc) is True (default: rate-limit messages), or
      - fn returns a value for which retryable_result(value) is True.

    Last attempt's exception is re-raised; last non-retryable result is returned.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if is_retryable is None:
        is_retryable = lambda exc: is_rate_limit_error(exc)  # noqa: E731

    last_exc: Optional[BaseException] = None
    last_result: Optional[T] = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = fn()
        except BaseException as exc:
            last_exc = exc
            if attempt >= max_attempts or not is_retryable(exc):
                raise
            _sleep_backoff(attempt, base_delay_s, jitter_s)
            continue

        last_result = result
        if (
            attempt < max_attempts
            and retryable_result is not None
            and retryable_result(result)
        ):
            _sleep_backoff(attempt, base_delay_s, jitter_s)
            continue
        return result

    if last_exc is not None:
        raise last_exc
    return last_result  # type: ignore[return-value]


def _sleep_backoff(attempt: int, base_delay_s: float, jitter_s: float) -> None:
    delay = base_delay_s * (2 ** (attempt - 1))
    if jitter_s > 0:
        delay += random.uniform(0, jitter_s)
    time.sleep(delay)


def should_cache_yf_payload(payload: object) -> bool:
    """
    cached_call predicate: never persist rate-limit failures (they would
    poison the 12h price cache and suppress retries on the next scan).
    """
    return not is_rate_limit_payload(payload)
