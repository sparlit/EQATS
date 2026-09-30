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


"""Typed adapter contract, source health, and explicit fallback routing."""


from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from importlib import import_module
from pkgutil import iter_modules
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


@dataclass(frozen=True)
class SourceHealth:
    provider: str
    datasets: list[str]
    state: str
    rate_limit_ok: bool
    calls: int
    failures: int
    last_success: str | None
    last_error: str | None


@dataclass(frozen=True)
class FetchResult:
    data: Any
    provider: str
    fetched_at: str


class SourceAdapter(Protocol):
    name: str
    datasets: Iterable[str]

    def fetch(self, *args: Any, **kwargs: Any) -> Any: ...

    def health(self) -> SourceHealth: ...

    def rate_limit_ok(self) -> bool: ...


class ProviderFetchError(RuntimeError):
    """Raised when no configured provider can return an acceptable result."""

    def __init__(self, dataset: str, errors: dict[str, str]):
        self.dataset = dataset
        self.errors = errors
        details = "; ".join(f"{name}: {error}" for name, error in errors.items())
        super().__init__(f"No provider returned {dataset}: {details}")


class RateWindow:
    def __init__(self, max_calls: int, window_seconds: int):
        if max_calls < 1 or window_seconds < 1:
            msg = "Rate window values must be positive"
            raise ValueError(msg)
        self.max_calls = max_calls
        self.window = timedelta(seconds=window_seconds)
        self._calls: deque[float] = deque()
        self._lock = Lock()

    def allow(self) -> bool:
        now = monotonic()
        with self._lock:
            cutoff = now - self.window.total_seconds()
            while self._calls and self._calls[0] <= cutoff:
                self._calls.popleft()
            return len(self._calls) < self.max_calls

    def consume(self) -> bool:
        now = monotonic()
        with self._lock:
            cutoff = now - self.window.total_seconds()
            while self._calls and self._calls[0] <= cutoff:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(now)
            return True


class BaseSourceAdapter:
    """Tracks per-process source health and enforces a local call budget."""

    name = "unnamed"
    datasets: Iterable[str] = ()

    def __init__(self, max_calls: int = 60, window_seconds: int = 60):
        self._rate_window = RateWindow(max_calls, window_seconds)
        self._calls = 0
        self._failures = 0
        self._last_success: str | None = None
        self._last_error: str | None = None
        self._lock = Lock()

    def rate_limit_ok(self) -> bool:
        return self._rate_window.allow()

    def health(self) -> SourceHealth:
        with self._lock:
            state = "unavailable" if self._last_error else "healthy" if self._last_success else "not_checked"
            return SourceHealth(
                provider=self.name,
                datasets=sorted(self.datasets),
                state=state,
                rate_limit_ok=self.rate_limit_ok(),
                calls=self._calls,
                failures=self._failures,
                last_success=self._last_success,
                last_error=self._last_error,
            )

    def _execute(self, operation: Callable[[], Any]) -> Any:
        if not self._rate_window.consume():
            msg = "local provider rate limit exceeded"
            raise RuntimeError(msg)
        with self._lock:
            self._calls += 1
        try:
            result = operation()
        except Exception as exc:
            with self._lock:
                self._failures += 1
                self._last_error = f"{type(exc).__name__}: {exc}"
            raise
        with self._lock:
            self._last_success = datetime.now().isoformat(timespec="seconds")
            self._last_error = None
        return result

    def record_error(self, message: str) -> None:
        with self._lock:
            self._failures += 1
            self._last_error = message


class SourceRegistry:
    def __init__(self):
        self._adapters: dict[str, SourceAdapter] = {}
        self._discovered = False
        self._lock = Lock()
        self._discovery_lock = Lock()

    def register(self, adapter: SourceAdapter) -> None:
        with self._lock:
            if adapter.name in self._adapters:
                msg = f"Duplicate data source: {adapter.name}"
                raise ValueError(msg)
            self._adapters[adapter.name] = adapter

    def discover(self) -> None:
        with self._discovery_lock:
            if self._discovered:
                return
            package = import_module("data_sources.adapters")
            for module in iter_modules(package.__path__, package.__name__ + "."):
                loaded = import_module(module.name)
                register_adapters = getattr(loaded, "register_adapters", None)
                if register_adapters is not None:
                    register_adapters(self)
            self._discovered = True

    def fetch(
        self,
        dataset: str,
        providers: Iterable[str],
        *args: Any,
        accept: Callable[[Any], bool] | None = None,
        **kwargs: Any,
    ) -> FetchResult:
        self.discover()
        accept_result = accept or (lambda value: True)
        errors: dict[str, str] = {}
        for provider_name in providers:
            adapter = self._adapters.get(provider_name)
            if adapter is None:
                errors[provider_name] = "provider is not registered"
                continue
            if dataset not in adapter.datasets:
                errors[provider_name] = f"provider does not support {dataset}"
                continue
            if not adapter.rate_limit_ok():
                errors[provider_name] = "provider rate limit exceeded"
                continue
            try:
                result = adapter.fetch(*args, **kwargs)
                if not accept_result(result):
                    errors[provider_name] = "provider result rejected"
                    record_error = getattr(adapter, "record_error", None)
                    if record_error is not None:
                        record_error("provider result rejected")
                    continue
                return FetchResult(
                    data=result,
                    provider=provider_name,
                    fetched_at=datetime.now().isoformat(timespec="seconds"),
                )
            except Exception as exc:
                errors[provider_name] = f"{type(exc).__name__}: {exc}"
        raise ProviderFetchError(dataset, errors)

    def health(self) -> list[dict[str, Any]]:
        self.discover()
        return [asdict(adapter.health()) for adapter in sorted(self._adapters.values(), key=lambda item: item.name)]


_registry = SourceRegistry()


def get_registry() -> SourceRegistry:
    return _registry
