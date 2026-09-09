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


import sqlite3
from pathlib import Path

import pytest
from v2.lifecycle import TradeState, new_position, transition
from v2.portfolio_store import PortfolioStore


def test_position_lifecycle_and_partial_exit():
    p = new_position("ABC", "POSITIONAL_3_6M", "2026-01-01", 100, 95, 110, 120, 10)
    assert p.state == TradeState.WATCH
    p = transition(p, "QUALIFY", "2026-01-02")
    p = transition(p, "ENTER", "2026-01-03", price=100)
    p = transition(p, "T1_HIT", "2026-01-10", price=110, partial_fraction=0.5)
    assert p.state == TradeState.PARTIAL
    assert p.remaining_quantity == 5
    assert p.realised_quantity == 5
    assert p.realised_pnl == 50
    assert p.stop == 100
    p = transition(p, "TRAIL", "2026-01-15", trailing_stop=106)
    assert p.state == TradeState.TRAILING
    assert p.stop == 106
    p = transition(p, "STOP_HIT", "2026-01-20", price=106)
    assert p.state == TradeState.CLOSED
    assert p.remaining_quantity == 0
    assert p.realised_pnl == 80


def test_invalid_transition_rejected():
    p = new_position("ABC", "SWING_1_3M", "2026-01-01", 100, 95, 110, 120)
    with pytest.raises(ValueError):
        transition(p, "T1_HIT", "2026-01-02")


def test_trailing_stop_never_moves_backward():
    p = new_position("ABC", "SWING_1_3M", "2026-01-01", 100, 95, 110, 120)
    p = transition(transition(p, "QUALIFY", "2026-01-02"), "ENTER", "2026-01-03")
    p = transition(p, "TRAIL", "2026-01-04", trailing_stop=98)
    with pytest.raises(ValueError):
        transition(p, "TRAIL", "2026-01-05", trailing_stop=97)


def test_portfolio_store_persists_events_and_watchlist(tmp_path: Path):
    db = tmp_path / "portfolio.db"
    store = PortfolioStore(db)
    store.initialize()
    p = new_position("XYZ", "POSITIONAL_6_12M", "2026-02-01", 200, 185, 225, 250, 4)
    store.save_position(p, "CREATE")
    previous = p.state
    p = transition(p, "QUALIFY", "2026-02-02")
    store.save_position(p, "QUALIFY", previous_state=previous)
    loaded = store.get_position(p.trade_id)
    assert loaded is not None
    assert loaded.state == TradeState.READY
    assert loaded.initial_stop == 185
    assert len(store.open_positions()) == 1
    store.remember_candidate("XYZ", "POSITIONAL_6_12M", "2026-02-02", 82.5)
    store.remember_candidate("XYZ", "POSITIONAL_6_12M", "2026-02-03", 79.0)


def test_portfolio_store_migrates_existing_position_table(tmp_path: Path):
    db = tmp_path / "legacy_portfolio.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE v2_positions (
            trade_id TEXT PRIMARY KEY, symbol TEXT, horizon TEXT, state TEXT,
            created_date TEXT, updated_date TEXT, entry REAL, stop REAL,
            target1 REAL, target2 REAL, quantity REAL, remaining_quantity REAL,
            realised_quantity REAL, last_price REAL, exit_price REAL, reason TEXT
        )""")
    store = PortfolioStore(db)
    store.initialize()
    position = new_position("ABC", "SWING_1_3M", "2026-01-01", 100, 95, 110, 120)
    store.save_position(position, "CREATE")
    loaded = store.get_position(position.trade_id)
    assert loaded is not None
    assert loaded.initial_stop == 95
