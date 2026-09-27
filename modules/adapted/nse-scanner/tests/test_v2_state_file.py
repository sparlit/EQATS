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


from v2.lifecycle import new_position, transition
from v2.portfolio_store import PortfolioStore
from v2.state_file import export_state_file, restore_state_file


def test_state_file_round_trip_preserves_position_pnl(tmp_path):
    first_db = tmp_path / "first.db"
    store = PortfolioStore(first_db)
    store.initialize()
    position = new_position("ABC", "SWING_1_3M", "2026-08-03", 100, 95, 110, 120, 10)
    position = transition(position, "QUALIFY", "2026-08-03", price=99)
    position = transition(position, "ENTER", "2026-08-03", price=100)
    position = transition(position, "T1_HIT", "2026-08-03", price=110)
    store.save_position(position, "T1_HIT")
    state_path = export_state_file(first_db, tmp_path / "v2_portfolio_state.json")
    second_db = tmp_path / "second.db"
    assert restore_state_file(second_db, state_path)
    restored = PortfolioStore(second_db).get_position(position.trade_id)
    assert restored is not None
    assert restored.realised_pnl == 50
    assert restored.remaining_quantity == 5
