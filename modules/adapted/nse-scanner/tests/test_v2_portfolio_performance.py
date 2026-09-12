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
from v2.portfolio_performance import build_portfolio_snapshot
from v2.portfolio_risk import PortfolioConfig, allocate_long_position
from v2.portfolio_summary import render_portfolio_summary


def test_allocation_respects_risk_and_position_limits():
    config = PortfolioConfig(capital_base=300_000, risk_per_trade_pct=0.01, max_position_pct=0.20)
    allocation = allocate_long_position(
        100,
        95,
        committed_capital=0,
        committed_risk=0,
        committed_positions=0,
        config=config,
    )
    assert allocation.quantity == 600
    assert allocation.entry_notional == 60_000
    assert allocation.initial_risk == 3_000
    assert allocation.binding_constraint in {"risk_budget_per_trade", "max_position_value"}


def test_partial_exit_and_snapshot_keep_realised_and_unrealised_pnl_separate():
    position = new_position("ABC", "SWING_1_3M", "2026-08-01", 100, 95, 110, 120, 10)
    position = transition(position, "QUALIFY", "2026-08-01", price=99)
    position = transition(position, "ENTER", "2026-08-01", price=100)
    position = transition(position, "T1_HIT", "2026-08-02", price=110, partial_fraction=0.5)
    position = transition(position, "MARK", "2026-08-02", price=112)
    snapshot = build_portfolio_snapshot([position], "2026-08-02", 300_000)
    assert snapshot.realised_pnl == 50
    assert snapshot.unrealised_pnl == 60
    assert snapshot.total_pnl == 110
    assert snapshot.open_risk_to_stops == 0
    assert "Total P&L: +₹110.00" in render_portfolio_summary(snapshot)
