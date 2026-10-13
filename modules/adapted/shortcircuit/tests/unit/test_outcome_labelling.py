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
An unknown result is not a breakeven, and an estimated cost basis is not a P&L.

Four of the twelve trades over 7-10 Sep 2026 reached `_finalize_closed_position`
with `exit_price=0.0` because no exit order was ever placed. Each was written to
the ML dataset as `PNL=0.00%`, outcome BREAKEVEN:

    [ML] Outcome recorded for NSE:GRAPHITE-EQ (obs=...) MFE=1.03% MAE=1.18% PNL=0.00%

Those four are precisely the trades that failed, so the dataset lost the rows it
most needed and gained four confident lies — against a corpus of 56 usable
training rows.

Separately, adoption falls back to LTP when it cannot read the real average
price. LTP is the price now, not the price paid: NSE:GRAPHITE-EQ was reported at
-₹23.40 when the real figure on those shares was -₹3.70.
"""

import asyncio

import pytest
from shortcircuit.execution.order_manager import OrderManager


class _MLSpy:
    def __init__(self):
        self.calls: list[dict] = []

    def update_outcome(self, **kw):
        self.calls.append(kw)


@pytest.fixture
def ml(monkeypatch):
    spy = _MLSpy()
    monkeypatch.setattr("shortcircuit.execution.order_manager.get_ml_logger", lambda: spy)
    return spy


def _manager(**pos_overrides):
    om = OrderManager(broker=None, telegram_bot=None)
    pos = {
        "symbol": "NSE:X-EQ",
        "qty": 2,
        "side": "SHORT",
        "status": "OPEN",
        "entry_price": 858.05,
        "obs_id": "obs-1",
        "entry_time": None,
        "mfe_pct": 1.03,
        "mae_pct": 1.18,
    }
    pos.update(pos_overrides)
    om.active_positions["NSE:X-EQ"] = pos
    return om


def _finalize(om, **kw):
    kw.setdefault("symbol", "NSE:X-EQ")
    kw.setdefault("reason", "TP_HIT")
    return asyncio.run(om._finalize_closed_position(**kw))


def test_a_real_exit_is_still_recorded(ml):
    _finalize(_manager(), exit_price=849.45, pnl=17.20)

    assert len(ml.calls) == 1
    assert ml.calls[0]["outcome"] == "WIN"


def test_a_real_breakeven_is_still_recorded(ml):
    """A genuine breakeven has a real fill price. Only that counts as one."""
    _finalize(_manager(), exit_price=858.05, pnl=0.0)

    assert len(ml.calls) == 1
    assert ml.calls[0]["outcome"] == "BREAKEVEN"


def test_an_unknown_exit_price_is_not_recorded_as_breakeven(ml, caplog):
    """The regression. exit_price == 0 means no fill price ever existed."""
    with caplog.at_level("WARNING"):
        _finalize(_manager(), exit_price=0.0, pnl=0.0)

    assert ml.calls == [], (
        "labelling an unresolved exit as BREAKEVEN put four fabricated rows into "
        "a 56-row training set"
    )
    assert any("UNRESOLVED" in r.message for r in caplog.records)


def test_an_estimated_cost_basis_is_not_recorded(ml):
    """P&L against an LTP fallback is arithmetic on a price nobody traded at."""
    _finalize(
        _manager(cost_basis_estimated=True, entry_price=848.20),
        exit_price=859.90,
        pnl=-23.40,
    )

    assert ml.calls == []


def test_a_verified_cost_basis_is_recorded(ml):
    _finalize(
        _manager(cost_basis_estimated=False),
        exit_price=849.45,
        pnl=17.20,
    )

    assert len(ml.calls) == 1


def test_the_position_is_still_closed_out_when_the_outcome_is_withheld(ml):
    """
    Skipping the ML row must not skip the cleanup — the capital slot and the
    registry entry are separate concerns from the dataset.
    """
    om = _manager()
    _finalize(om, exit_price=0.0, pnl=0.0)

    assert "NSE:X-EQ" not in om.active_positions
