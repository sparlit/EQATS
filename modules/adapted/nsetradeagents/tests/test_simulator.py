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


from app.portfolio.simulator import PortfolioSimulator

TRADE_RESULT = {
    "ticker": "TITAN.NS",
    "price": 500.0,
    "quantity": 50,
    "position_size_inr": 25000.0,
    "stop_loss": 465.0,
    "take_profit": 590.0,
    "confidence": 85,
    "reasoning": "Strong uptrend",
}

TECHNICAL = {"summary": "Bullish MACD crossover"}


def test_open_trade(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    trade = sim.open_trade(TRADE_RESULT, TECHNICAL)

    assert trade is not None
    assert trade.ticker == "TITAN.NS"
    assert trade.entry_price == 500.0
    assert trade.quantity == 50
    assert trade.status == "open"
    assert trade.stop_loss == 465.0
    assert trade.take_profit == 590.0


def test_open_trade_duplicate_blocked(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    first = sim.open_trade(TRADE_RESULT, TECHNICAL)
    second = sim.open_trade(TRADE_RESULT, TECHNICAL)

    assert first is not None
    assert second is None


def test_open_trade_insufficient_funds(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 10000)

    sim = PortfolioSimulator()
    trade = sim.open_trade(TRADE_RESULT, TECHNICAL)

    assert trade is None


def test_close_trade(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    sim.open_trade(TRADE_RESULT, TECHNICAL)
    trade = sim.close_trade("TITAN.NS", 550.0, "target")

    assert trade is not None
    assert trade.status == "closed"
    assert trade.close_price == 550.0
    assert trade.close_reason == "target"
    assert trade.pnl == 2500.0  # (550 - 500) * 50 shares
    assert trade.pnl_pct == 10.0  # 10% gain


def test_close_trade_not_found(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    trade = sim.close_trade("RELIANCE.NS", 550.0, "target")

    assert trade is None


def test_save_snapshot(mock_db, monkeypatch):
    monkeypatch.setattr("app.portfolio.simulator.settings.starting_capital", 100000)

    sim = PortfolioSimulator()
    sim.open_trade(TRADE_RESULT, TECHNICAL)
    snapshot = sim.save_snapshot()

    assert snapshot is not None
    assert snapshot.open_positions == 1
    assert snapshot.invested == 25000.0
    assert snapshot.cash == 75000.0
    assert snapshot.total_value == 100000.0
