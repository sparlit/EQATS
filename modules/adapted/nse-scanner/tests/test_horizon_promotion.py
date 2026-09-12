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


from datetime import date

import pandas as pd
from v2.horizon_promotion import apply_monthly_promotions, assess_promotion
from v2.lifecycle import new_position, transition
from v2.portfolio_store import PortfolioStore


def _frame(sessions=80):
    dates = pd.bdate_range("2026-01-01", periods=sessions)
    return pd.DataFrame(
        {
            "symbol": "ABC",
            "trade_date": dates,
            "open": [100.0] * sessions,
            "high": [102.0] * sessions,
            "low": [99.0] * sessions,
            "close": [101.0] * sessions,
            "volume": [100000] * sessions,
        }
    )


def _open_position():
    p = new_position("ABC", "SWING_1_3M", "2026-01-02", 100, 90, 110, 120, quantity=10)
    return transition(transition(p, "QUALIFY", "2026-01-03", price=101), "ENTER", "2026-01-03", price=100)


def _signals(*_args, **_kwargs):
    return {"daily_bullish": True, "weekly_bullish": True, "kama_rising": True, "stretched": False, "chop": False}


def test_open_profitable_swing_promotes(monkeypatch):
    monkeypatch.setattr("v2.horizon_promotion.fixed_hybrid_hull_signals", _signals)
    position = transition(_open_position(), "MARK", "2026-04-24", price=112)
    decision = assess_promotion(position, _frame())
    assert decision.promoted
    assert decision.target_horizon == "POSITIONAL_3_6M"
    assert decision.current_r == 1.2


def test_promotion_needs_one_r_profit(monkeypatch):
    monkeypatch.setattr("v2.horizon_promotion.fixed_hybrid_hull_signals", _signals)
    position = transition(_open_position(), "MARK", "2026-04-24", price=105)
    assert "one_r_profit_cushion_not_reached" in assess_promotion(position, _frame()).reasons


def test_promotion_preserves_stop_and_pnl(monkeypatch, tmp_path):
    monkeypatch.setattr("v2.horizon_promotion.fixed_hybrid_hull_signals", _signals)
    store = PortfolioStore(tmp_path / "portfolio.db")
    store.initialize()
    position = transition(_open_position(), "MARK", "2026-04-24", price=112)
    store.save_position(position, "CREATE")
    decisions = apply_monthly_promotions(store, _frame(), date(2026, 4, 24).isoformat())
    saved = store.get_position(position.trade_id)
    assert decisions[0].promoted
    assert saved.horizon == "POSITIONAL_3_6M"
    assert saved.stop == position.stop
    assert saved.realised_pnl == position.realised_pnl
    with store.connect() as conn:
        event = conn.execute("SELECT event_type FROM v2_position_events ORDER BY event_id DESC LIMIT 1").fetchone()
    assert event["event_type"] == "HORIZON_PROMOTE"
