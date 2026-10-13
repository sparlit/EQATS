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


import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "scripts" / "thetadata_live_adapter.py"
SPEC = importlib.util.spec_from_file_location("thetadata_live_adapter", ADAPTER_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def test_contract_normalization_is_bounded_and_keeps_oi_availability() -> None:
    rows = []
    oi = {}
    for index in range(20):
        strike = 90 + index
        for right in ("CALL", "PUT"):
            rows.append(
                {
                    "expiration": "2026-09-04",
                    "strike": strike,
                    "right": right,
                    "bid": 1.0,
                    "ask": 1.2,
                    "bid_size": 10,
                    "ask_size": 12,
                    "timestamp": "2026-08-28T15:00:00-04:00",
                }
            )
            oi[("2026-09-04", strike * 1_000, right)] = index

    normalized = adapter._normalize_contracts(
        "SPY",
        rows,
        oi,
        {"2026-09-04"},
        100.0,
        0.10,
        12,
    )

    assert len(normalized) == 12
    assert all(row["symbol"].startswith("SPY260904") for row in normalized)
    assert all(row["open_interest"] is not None for row in normalized)
    assert {row["right"] for row in normalized} == {"CALL", "PUT"}


def test_ndjson_ping_does_not_require_provider_credentials() -> None:
    completed = subprocess.run(
        [sys.executable, "-u", str(ADAPTER_PATH)],
        input='{"id":7,"op":"ping"}\n',
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    response = json.loads(completed.stdout)

    assert response == {
        "id": 7,
        "ok": True,
        "result": {"provider": "thetadata", "connected": False},
    }
    assert "password" not in completed.stdout.lower()
