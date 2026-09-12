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
Tests for the runtime/usability fixes:

- MarketDataManager.refresh() advances data each cycle (was: yfinance fetched once + frozen).
- HistoryManager seeds a synthetic history when YFinance is unavailable, so indicators (and
  the agent pipeline) can still run end-to-end.
"""

from src.market.history_manager import HistoryManager
from src.market.indicators import Timeframe, calculate_indicators
from src.market.manager import MarketDataManager
from src.market.signals import SignalEngine


def test_manager_refresh_advances_simulated():
    manager = MarketDataManager(symbols=["RELIANCE", "TCS", "SBIN"])
    manager.is_live = False
    manager.data_source = "simulated"
    manager._load_simulated_quotes()

    before = {s: q.change_percent for s, q in manager.get_all_quotes().items()}
    manager.refresh()
    after = {s: q.change_percent for s, q in manager.get_all_quotes().items()}

    assert before  # there were quotes
    assert before != after  # refresh advanced the simulated movement


def test_history_manager_seeds_synthetic():
    hm = HistoryManager(symbols=[])
    hm._seed_synthetic("DEMO", bars=150)
    df = hm.get_history("DEMO")
    assert df is not None
    assert len(df) == 150
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_prefetch_seeds_synthetic_on_failure(monkeypatch):
    hm = HistoryManager(symbols=["AAA", "BBB"])
    # Simulate YFinance being unavailable.
    monkeypatch.setattr(hm, "fetch_history", lambda *a, **k: False)
    results = hm.prefetch_all()
    assert all(results.values())  # synthetic seeded -> reported available
    assert hm.has_sufficient_data("AAA")


def test_synthetic_history_drives_indicators_and_signals():
    # End-to-end: synthetic history -> real indicators -> SignalEngine produces output
    # without raising (proves the agent pipeline can run offline).
    hm = HistoryManager(symbols=[])
    hm._seed_synthetic("DEMO", bars=180)
    df = hm.get_history("DEMO", bars=200, include_forming=False)
    indicators = calculate_indicators(df, "DEMO", timeframe=Timeframe.D1)
    assert indicators.rsi is not None
    # Should not raise; may or may not produce signals depending on the random walk.
    signals = SignalEngine().generate_signals(indicators)
    assert isinstance(signals, list)
