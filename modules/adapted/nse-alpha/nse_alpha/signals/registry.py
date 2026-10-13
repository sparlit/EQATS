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


"""Signal registry — decorator-based registration with schema enforcement.

Each signal must declare:
    name        Unique identifier (snake_case)
    family      Signal family (e.g. "Momentum", "Reversal")
    lookback    Lookback window in trading days
    rationale   One-line economic rationale — REQUIRED, non-empty

Signals registered here can be retrieved via ``REGISTRY`` or ``get_all_signals()``.
The registry enforces the hard rules:
    1. ``rationale`` must not be empty.
    2. All signals have signature ``(panel: pd.DataFrame, **params) -> pd.Series``.
    3. The registry does NOT call or validate signal logic — that is the canary
       tests' job.

Usage::

    from nse_alpha.signals.registry import register, REGISTRY

    @register(name="my_signal", family="Momentum", lookback=252, rationale="...")
    def my_signal(panel: pd.DataFrame, **params: object) -> pd.Series:
        ...
"""


from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SignalMeta:
    """Metadata attached to every registered signal."""

    name: str
    family: str
    lookback_days: int
    rationale: str


# Global registry: name → (meta, callable)
REGISTRY: dict[str, tuple[SignalMeta, Callable[..., pd.Series]]] = {}


def register(
    *,
    name: str,
    family: str,
    lookback_days: int,
    rationale: str,
) -> Callable[[Callable[..., pd.Series]], Callable[..., pd.Series]]:
    """Decorator to register a signal function.

    Parameters
    ----------
    name:
        Unique snake_case identifier.
    family:
        One of: "Momentum", "Reversal", "Volatility", "Liquidity", "Range".
    lookback_days:
        Number of trading days of history the signal consumes.
    rationale:
        One-line economic rationale.  Must not be empty.

    Raises
    ------
    ValueError
        If ``rationale`` is empty, or if ``name`` is already registered.
    """
    if not rationale.strip():
        raise ValueError(
            f"Signal '{name}' must have a non-empty rationale. "
            "Every signal must have an economic justification."
        )

    def _decorator(fn: Callable[..., pd.Series]) -> Callable[..., pd.Series]:
        if name in REGISTRY:
            raise ValueError(
                f"Signal '{name}' is already registered. Use a unique name for each signal."
            )
        meta = SignalMeta(
            name=name,
            family=family,
            lookback_days=lookback_days,
            rationale=rationale,
        )
        REGISTRY[name] = (meta, fn)
        return fn

    return _decorator


def get_all_signals() -> list[tuple[SignalMeta, Callable[..., pd.Series]]]:
    """Return all registered (meta, fn) pairs, sorted by family then name."""
    return sorted(REGISTRY.values(), key=lambda x: (x[0].family, x[0].name))


def get_signal(name: str) -> tuple[SignalMeta, Callable[..., pd.Series]]:
    """Retrieve a registered signal by name.

    Raises
    ------
    KeyError
        If the signal is not found.
    """
    if name not in REGISTRY:
        available = sorted(REGISTRY.keys())
        raise KeyError(f"Signal '{name}' not registered. Available signals: {available}")
    return REGISTRY[name]


def _import_all_signal_modules() -> None:
    """Force-import all signal modules so that @register decorators execute."""
    import importlib

    modules = [
        "nse_alpha.signals.momentum",
        "nse_alpha.signals.reversal",
        "nse_alpha.signals.volatility",
        "nse_alpha.signals.liquidity",
        "nse_alpha.signals.range_",
    ]
    for mod_name in modules:
        importlib.import_module(mod_name)


def load_all_signals() -> None:
    """Ensure all signal modules are imported and registered.

    Call this once before iterating ``REGISTRY``.
    """
    _import_all_signal_modules()
