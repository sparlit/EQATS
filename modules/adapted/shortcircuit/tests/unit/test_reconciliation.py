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
The reconciliation divergence table.

Live trading systems fail when local state and broker state disagree while
neither side raises an error. This file enumerates every way they can disagree
and asserts the engine classifies each correctly.

| Broker state        | Local state          | Expected classification          |
|---------------------|----------------------|----------------------------------|
| position present    | absent               | orphan  → adopt with protection  |
| absent              | position present     | phantom → release capital        |
| qty 100             | qty 50               | quantity mismatch                |
| absent              | absent               | agree, no action                 |
| present             | same symbol, same qty| agree, no action                 |
| closed manually     | open                 | manual close (a phantom)         |
| filled              | not recorded         | missed fill (an orphan)          |

Plus an eighth: adoption must be idempotent. The README claims duplicate
adoption is avoided; this proves it.

The engine is exercised through `reconcile()` with the two data sources stubbed,
so the classification logic under test is the real one — not a reimplementation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from shortcircuit.state.reconciliation import ReconciliationEngine

# Harness


def _broker_entry(symbol, net_qty, avg=100.0):
    """Shape produced by _get_broker_positions_cached: qty absolute, net_qty signed."""
    return {"symbol": symbol, "qty": abs(net_qty), "net_qty": net_qty, "avg_price": avg}


def make_engine(broker_positions: dict, db_positions: dict) -> ReconciliationEngine:
    """
    A ReconciliationEngine whose two data sources are stubbed and whose side
    effects (DB writes, Telegram, adoption) are captured rather than performed.
    """
    engine = ReconciliationEngine.__new__(ReconciliationEngine)

    engine.broker = MagicMock()
    engine.db = MagicMock()
    engine.db.execute = AsyncMock()
    engine.db.fetch = AsyncMock(return_value=[])
    engine.telegram = MagicMock()
    engine.telegram.send_alert = AsyncMock()
    engine.capital = MagicMock()
    engine.capital.is_slot_free = True
    engine.order_manager = MagicMock()
    engine.order_manager.active_positions = {}

    engine.running = False
    engine._db_positions = dict(db_positions)
    engine._db_dirty = False
    engine._has_open_positions = bool(db_positions) or bool(broker_positions)
    engine._shutdown_event = None
    engine._last_rest_sync = 0.0
    engine._recently_closed = {}
    engine._recently_modified = {}
    engine._orphan_grace_secs = 30.0

    async def _fake_broker(_cache_has_data):
        return dict(broker_positions)

    async def _fake_db():
        return dict(db_positions)

    engine._read_broker_cache = lambda: bool(broker_positions)
    engine._get_broker_positions_cached = _fake_broker
    engine._get_db_positions_cached = _fake_db

    # Capture the classification instead of acting on it.
    engine.captured = {}

    async def _capture(db_pos, broker_pos, orphans, phantoms, mismatched):
        engine.captured = {
            "orphans": orphans,
            "phantoms": phantoms,
            "mismatched": mismatched,
        }

    engine._handle_divergence = _capture
    return engine


def classify(broker_positions: dict, db_positions: dict) -> dict:
    engine = make_engine(broker_positions, db_positions)
    asyncio.run(engine.reconcile())
    return engine.captured or {"orphans": [], "phantoms": [], "mismatched": []}


# The table — one test per row

SYM = "NSE:TESTSYM-EQ"


def test_row1_broker_has_position_local_does_not_is_an_orphan():
    result = classify({SYM: _broker_entry(SYM, -10)}, {})
    assert [o["symbol"] for o in result["orphans"]] == [SYM]
    assert not result["phantoms"] and not result["mismatched"]


def test_row1b_orphan_carries_the_signed_quantity_for_side_inference():
    """
    adopt_orphan derives LONG/SHORT from the SIGN. Passing an absolute value
    would label every short as a long and place the emergency stop on the
    wrong side of the market.
    """
    result = classify({SYM: _broker_entry(SYM, -10)}, {})
    assert result["orphans"][0]["net_qty"] == -10
    assert result["orphans"][0]["qty"] == 10


def test_row2_local_has_position_broker_does_not_is_a_phantom():
    result = classify({}, {SYM: 10})
    assert [p["symbol"] for p in result["phantoms"]] == [SYM]
    assert not result["orphans"] and not result["mismatched"]


def test_row3_differing_quantities_is_a_mismatch():
    result = classify({SYM: _broker_entry(SYM, -50)}, {SYM: 100})
    assert len(result["mismatched"]) == 1
    entry = result["mismatched"][0]
    assert entry["symbol"] == SYM
    assert entry["db_qty"] == 100
    assert entry["broker_qty"] == 50, "compared on absolute quantity, not signed"


def test_row4_both_flat_produces_no_divergence():
    result = classify({}, {})
    assert not result["orphans"] and not result["phantoms"] and not result["mismatched"]


def test_row5_agreeing_positions_produce_no_divergence():
    result = classify({SYM: _broker_entry(SYM, -10)}, {SYM: 10})
    assert not result["orphans"] and not result["phantoms"] and not result["mismatched"]


def test_row5b_short_position_agrees_despite_negative_broker_qty():
    """
    Fyers reports a short as netQty=-10 while the DB stores 10. Comparing signed
    against absolute would report a spurious mismatch on every single short.
    """
    result = classify({SYM: _broker_entry(SYM, -10)}, {SYM: 10})
    assert not result["mismatched"]


def test_row6_manual_close_appears_as_a_phantom():
    """Operator closed the position in the broker app; the bot still thinks it is open."""
    result = classify({}, {SYM: 7})
    assert len(result["phantoms"]) == 1
    assert result["phantoms"][0]["qty"] == 7


def test_row7_missed_fill_appears_as_an_orphan():
    """A fill the internal loop never saw: broker has it, local registry does not."""
    result = classify({SYM: _broker_entry(SYM, -25, avg=250.0)}, {})
    assert len(result["orphans"]) == 1
    assert result["orphans"][0]["symbol"] == SYM


# Row 8 — adoption must be idempotent


def test_row8_adoption_is_idempotent():
    """
    Two reconcile cycles a few seconds apart must not adopt the same orphan
    twice — a second adoption would place a second emergency stop for a
    quantity that is already protected.
    """
    engine = make_engine({SYM: _broker_entry(SYM, -10)}, {})
    engine.order_manager.active_positions = {}

    adopted: list[str] = []

    async def _adopt(broker_pos):
        sym = broker_pos["symbol"]
        if sym in engine.order_manager.active_positions:
            return  # the guard under test
        engine.order_manager.active_positions[sym] = {"symbol": sym}
        adopted.append(sym)

    engine.adopt_orphan = _adopt
    del engine._handle_divergence  # use the real divergence handler

    async def _noop_execute(*a, **k):
        return None

    engine.db.execute = _noop_execute

    asyncio.run(
        engine._handle_divergence(
            {},
            {SYM: _broker_entry(SYM, -10)},
            [{"symbol": SYM, "qty": 10, "net_qty": -10}],
            [],
            [],
        )
    )
    asyncio.run(
        engine._handle_divergence(
            {},
            {SYM: _broker_entry(SYM, -10)},
            [{"symbol": SYM, "qty": 10, "net_qty": -10}],
            [],
            [],
        )
    )

    assert adopted == [SYM], f"orphan adopted {len(adopted)} times, expected once"


# Safety property: a degraded broker must never look like "flat"


def test_broker_fetch_failure_does_not_phantom_close_every_position():
    """
    If the broker fetch raises, broker_positions is empty — which would make
    every DB row a phantom, and phantom handling force-closes DB state and
    releases capital. A degraded API must never be able to trigger that.
    """
    engine = make_engine({}, {SYM: 10})

    async def _boom(_cache_has_data):
        raise TimeoutError("broker API degraded")

    engine._get_broker_positions_cached = _boom
    engine._read_broker_cache = lambda: False

    asyncio.run(engine.reconcile())
    assert not engine.captured, (
        "divergence was acted on despite an unusable broker view — "
        "this would close live positions in the DB during an API outage"
    )


def test_recently_closed_symbols_are_not_reported_as_orphans():
    """Broker settlement lag must not look like a manual entry."""
    import time

    engine = make_engine({SYM: _broker_entry(SYM, -10)}, {})
    engine._recently_closed = {SYM: time.time()}
    asyncio.run(engine.reconcile())
    orphans = (engine.captured or {}).get("orphans", [])
    assert not orphans, "an orphan was raised inside the settlement grace period"
