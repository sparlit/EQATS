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
Structural test: the Brain must not depend on the Muscle.

The README claims trading intelligence is sealed inside `strategy/`, knowing
nothing about brokers, sockets or Telegram. That is an architectural claim, and
architectural claims decay silently — one convenient import during a late-night
debugging session and it is quietly false.

This converts the claim into a verified fact by parsing the AST of every module
under `strategy/` and inspecting what it imports.
"""

import ast
from pathlib import Path

import pytest

STRATEGY_DIR = Path(__file__).resolve().parents[2] / "src" / "shortcircuit" / "strategy"

# Modules in the runtime layer. `strategy/` importing any of these would mean the
# Brain has reached into the Muscle.
RUNTIME_MODULES = {
    "fyers_broker_interface",
    "fyers_connect",
    "order_manager",
    "focus_engine",
    "trade_manager",
    "capital_manager",
    "telegram_bot",
    "database",
    "reconciliation",
    "scanner",
    "analyzer",
    "main",
    "ml_logger",
    "gate_result_logger",
    "signal_manager",
    "market_session",
    "startup_recovery",
    "eod_analyzer",
    "eod_scheduler",
    "eod_watchdog",
}

# Third-party packages that would imply I/O from inside the Brain.
FORBIDDEN_THIRD_PARTY = {
    "fyers_apiv3",
    "telegram",
    "asyncpg",
    "psycopg2",
    "requests",
    "aiohttp",
    "httpx",
    "websockets",
}

# `config` and `rest_limiter` are deliberately permitted: the Brain reads
# thresholds, and market_context paces its own REST calls for the index series.
ALLOWED_RUNTIME_IMPORTS = {"config", "rest_limiter", "symbols"}


def _strategy_modules() -> list[Path]:
    return sorted(p for p in STRATEGY_DIR.glob("*.py") if p.name != "__init__.py")


def _imported_roots(path: Path) -> set[str]:
    """Top-level package name of every import in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, stays inside the package
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_strategy_directory_exists():
    assert STRATEGY_DIR.is_dir(), f"strategy/ not found at {STRATEGY_DIR}"


def test_strategy_has_modules():
    assert _strategy_modules(), "no strategy modules found — the test would pass vacuously"


@pytest.mark.parametrize("module", _strategy_modules(), ids=lambda p: p.name)
def test_strategy_module_does_not_import_the_runtime_layer(module: Path):
    offenders = (_imported_roots(module) & RUNTIME_MODULES) - ALLOWED_RUNTIME_IMPORTS
    assert not offenders, (
        f"{module.name} imports runtime module(s) {sorted(offenders)}. "
        f"The Brain must not depend on the Muscle."
    )


@pytest.mark.parametrize("module", _strategy_modules(), ids=lambda p: p.name)
def test_strategy_module_does_not_import_io_libraries(module: Path):
    """
    market_context and htf_confluence receive an injected `fyers` client, which
    is the correct pattern — they never import the SDK themselves.
    """
    offenders = _imported_roots(module) & FORBIDDEN_THIRD_PARTY
    assert not offenders, (
        f"{module.name} imports I/O library/libraries {sorted(offenders)}. "
        f"The Brain should receive clients by injection, never import them."
    )


def test_no_strategy_module_opens_a_file():
    """Reading or writing files from inside the Brain would make it stateful."""
    offenders = []
    for module in _strategy_modules():
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "open":
                    offenders.append(module.name)
    assert not offenders, f"strategy modules performing file I/O: {sorted(set(offenders))}"


def test_the_allowlist_is_documented_not_accidental():
    """
    Guards the guard: if someone widens ALLOWED_RUNTIME_IMPORTS to make a failure
    go away, this forces the list to stay small and deliberate.
    """
    assert {"config", "rest_limiter", "symbols"} == ALLOWED_RUNTIME_IMPORTS, (
        "The Brain's permitted runtime imports changed. This is an architectural "
        "decision — update docs/DECISIONS.md before widening it."
    )
