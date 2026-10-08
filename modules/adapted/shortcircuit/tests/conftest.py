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
Shared fixtures and safety guards for the ShortCircuit test suite.

Two principles hold throughout:

1. **Unit tests never touch the network.** This is enforced structurally by the
   `no_network` autouse fixture below, not by convention. A test that
   accidentally reaches a live broker API fails loudly instead of quietly
   passing (or quietly placing an order).

2. **Every fixture is deterministic.** No `random`, no `datetime.now()`, no
   dependence on the machine's timezone. A test that passes at 09:00 and fails
   at 15:30 is worse than no test.
"""

import os
import socket
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

# src/ layout: the package lives under src/, so that is what goes on the path.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

IST = timezone(timedelta(hours=5, minutes=30))


# Safety guards


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    """
    Block outbound sockets in unit and property tests.

    Integration tests opt out via the `integration` marker, because they
    legitimately talk to a local PostgreSQL instance.
    """
    if "integration" in request.keywords:
        return

    def guard(*args, **kwargs):
        raise RuntimeError(
            "network access attempted in a unit test — "
            "mock the broker or mark the test @pytest.mark.integration"
        )

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket.socket, "connect_ex", guard)


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch, request):
    """
    Ensure tests never pick up the developer's real `.env` values.

    Without this, a test asserting "config loads" would pass on the author's
    machine using live broker credentials and fail everywhere else.
    """
    if "integration" in request.keywords:
        return
    for key in (
        "FYERS_CLIENT_ID",
        "FYERS_SECRET_ID",
        "FYERS_ACCESS_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "DB_PASS",
        "DB_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)


# Candle fixtures — deterministic OHLCV frames


def _frame(rows: list[tuple]) -> pd.DataFrame:
    """rows: (open, high, low, close, volume) → DataFrame with an epoch column."""
    base = int(datetime(2026, 8, 3, 9, 15, tzinfo=IST).timestamp())
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df.insert(0, "epoch", [base + 60 * i for i in range(len(df))])
    return df


@pytest.fixture
def flat_candles() -> pd.DataFrame:
    """30 identical bars. VWAP must equal the price; slopes must be zero."""
    return _frame([(100.0, 100.0, 100.0, 100.0, 1_000)] * 30)


@pytest.fixture
def trending_candles() -> pd.DataFrame:
    """30 bars rising one rupee a bar, constant volume."""
    return _frame([(100.0 + i, 101.0 + i, 99.5 + i, 100.5 + i, 1_000) for i in range(30)])


@pytest.fixture
def sample_candles() -> pd.DataFrame:
    """
    40 bars: a rise, a blow-off on heavy volume, then fading volume and a roll
    over. Shaped to exercise the exhaustion gates without asserting a signal.
    """
    rows = []
    for i in range(20):  # steady climb
        rows.append((100.0 + i, 100.8 + i, 99.6 + i, 100.6 + i, 1_000 + 20 * i))
    for i in range(5):  # blow-off, volume spike
        p = 120.0 + i * 1.5
        rows.append((p, p + 2.0, p - 0.4, p + 1.6, 6_000))
    for i in range(15):  # fade and roll over
        p = 127.0 - i * 0.4
        rows.append((p, p + 0.3, p - 0.8, p - 0.5, 1_400 - 60 * i))
    return _frame(rows)


@pytest.fixture
def single_bar() -> pd.DataFrame:
    return _frame([(100.0, 101.0, 99.0, 100.5, 500)])


@pytest.fixture
def zero_volume_candles() -> pd.DataFrame:
    """Volume is zero throughout — every volume-weighted calculation must not blow up."""
    return _frame([(100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 0) for i in range(20)])


# Broker / local state fixtures for the reconciliation divergence table


@pytest.fixture
def broker_position_factory():
    """
    Build a broker position record in the shape Fyers actually returns.

    Fyers reports BOTH `qty` (absolute) and `netQty` (signed, negative for a
    short), and both go to zero when flat. Different call sites historically
    read different keys, so fixtures mirror the real shape exactly.
    """

    def make(symbol="NSE:TESTSYM-EQ", net_qty=-10, avg=100.0):
        return {
            "symbol": symbol,
            "netQty": net_qty,
            "qty": abs(net_qty),
            "netAvg": avg,
            "avgPrice": avg,
            "buyAvg": 0.0 if net_qty < 0 else avg,
            "sellAvg": avg if net_qty < 0 else 0.0,
            "productType": "INTRADAY",
            "side": -1 if net_qty < 0 else 1,
            "realized_profit": 0,
            "unrealized_profit": 0,
        }

    return make


@pytest.fixture
def fake_broker_state(broker_position_factory):
    return {"NSE:TESTSYM-EQ": broker_position_factory()}


@pytest.fixture
def fake_local_state():
    """Internal registry shape used by OrderManager.active_positions."""
    return {
        "NSE:TESTSYM-EQ": {
            "symbol": "NSE:TESTSYM-EQ",
            "qty": 10,
            "side": "SHORT",
            "status": "OPEN",
            "entry_price": 100.0,
            "stop_loss": 102.0,
            "entry_id": "TEST_ENTRY_1",
            "sl_id": "TEST_SL_1",
        }
    }


# Broker funds responses — every shape the parser has had to handle


@pytest.fixture
def funds_responses() -> dict:
    """
    Balances are deliberately round and obviously synthetic. See
    tests/fixtures/README.md for the redaction policy.
    """
    return {
        "v3_fund_limit": {
            "s": "ok",
            "fund_limit": [
                {"id": 1, "title": "Total Balance", "equityAmount": 5000.0},
                {"id": 2, "title": "Utilized Amount", "equityAmount": 1000.0},
                {"id": 10, "title": "Available Balance", "equityAmount": 4000.0},
            ],
        },
        "title_only": {
            "s": "ok",
            "fund_limit": [
                {"id": 99, "title": "Available Balance", "equityAmount": 2500.0},
            ],
        },
        "equity_dict": {"s": "ok", "equity": {"available_margin": 3000.0}},
        "flat_dict": {"s": "ok", "available_margin": 1500.0},
        "error": {"s": "error", "message": "invalid token"},
        "malformed": {"s": "ok", "unexpected_key": []},
    }


@pytest.fixture
def frozen_now() -> datetime:
    """Fixed instant used with freezegun. A Monday, mid-session, IST."""
    return datetime(2026, 8, 3, 11, 30, 0, tzinfo=IST)
