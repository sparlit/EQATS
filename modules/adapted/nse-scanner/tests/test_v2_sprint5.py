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
from v2.freshness import assess_freshness
from v2.orchestrator import _equal_weight_benchmark, _warning_header
from v2.telegram_delivery import send_messages


def test_fresh_prices_and_indices():
    prices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-07-28"])})
    indices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-07-28"])})
    status = assess_freshness(prices, indices, date(2026, 7, 29))
    assert not status.prices_stale
    assert not status.indices_stale
    assert not status.degraded


def test_missing_index_is_degraded_but_explicit():
    prices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-07-28"])})
    indices = pd.DataFrame(columns=["trade_date"])
    status = assess_freshness(prices, indices, date(2026, 7, 29))
    assert not status.prices_stale
    assert status.indices_stale
    assert "index_history_missing" in status.reasons
    header = _warning_header(status, "EQUAL_WEIGHT_UNIVERSE_FALLBACK")
    assert "equal_weight_fallback" in header


def test_stale_price_history_blocks_new_signal_mode():
    prices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-07-20"])})
    indices = pd.DataFrame({"trade_date": pd.to_datetime(["2026-07-28"])})
    status = assess_freshness(prices, indices, date(2026, 7, 29))
    assert status.prices_stale
    assert "price_history_9_days_old" in status.reasons


def test_equal_weight_benchmark_is_reproducible():
    dates = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02"])
    prices = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "trade_date": dates,
            "close": [100.0, 110.0, 200.0, 220.0],
        }
    )
    benchmark = _equal_weight_benchmark(prices)
    assert list(benchmark.columns) == ["trade_date", "close"]
    assert benchmark.iloc[-1]["close"] == 1100.0


def test_telegram_is_dry_run_by_default(monkeypatch):
    monkeypatch.delenv("V3_TELEGRAM_BOT_TOKEN", raising=False)
    result = send_messages(["one", "two"])
    assert not result.sent
    assert result.message_count == 0
    assert result.reason == "dry_run"


def test_telegram_enabled_without_credentials_fails_closed(monkeypatch):
    for key in ["V3_TELEGRAM_BOT_TOKEN", "V3_TELEGRAM_CHAT_ID", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]:
        monkeypatch.delenv(key, raising=False)
    result = send_messages(["one"], enabled=True)
    assert not result.sent
    assert result.reason == "telegram_credentials_missing"
