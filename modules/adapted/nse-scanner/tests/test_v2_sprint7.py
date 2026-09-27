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


import numpy as np
import pandas as pd
from v2.backtest import BacktestTrade, run_point_in_time_backtest
from v2.performance import summarize_performance
from v2.walk_forward import score_sensitivity


def _prices(sessions: int = 180) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=sessions)
    rows = []
    for symbol, offset in [("AAA", 0.0), ("BBB", 5.0)]:
        close = 100 + offset + np.linspace(0, 45, sessions)
        volume = np.full(sessions, 1_000_000.0)
        volume[-20:] = 2_000_000.0
        for i, trade_date in enumerate(dates):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": close[i] - 0.2,
                    "high": close[i] + 1.0,
                    "low": close[i] - 1.0,
                    "close": close[i],
                    "volume": volume[i],
                }
            )
    return pd.DataFrame(rows)


def test_backtest_is_deterministic_and_point_in_time() -> None:
    prices = _prices()
    first = run_point_in_time_backtest(prices, minimum_score=0, warmup_sessions=120, max_positions=2)
    second = run_point_in_time_backtest(prices, minimum_score=0, warmup_sessions=120, max_positions=2)
    assert [(t.symbol, t.signal_date, t.realised_r) for t in first] == [
        (t.symbol, t.signal_date, t.realised_r) for t in second
    ]
    assert all(t.signal_date <= t.exit_date for t in first if t.exit_date)


def test_performance_report_uses_r_units() -> None:
    base = {
        "trade_id": "x",
        "symbol": "AAA",
        "horizon": "SWING_1_3M",
        "setup": "BREAKOUT",
        "signal_date": "2026-01-01",
        "entry_date": "2026-01-02",
        "exit_date": "2026-01-10",
        "entry": 100.0,
        "initial_stop": 95.0,
        "target1": 105.0,
        "target2": 110.0,
        "exit_price": 105.0,
        "state": "CLOSED",
        "holding_sessions": 5,
        "score": 80.0,
        "exit_reason": "test",
    }
    trades = [BacktestTrade(realised_r=1.0, **base), BacktestTrade(realised_r=-1.0, **{**base, "trade_id": "y"})]
    report = summarize_performance(trades)
    assert report.entered_trades == 2
    assert report.win_rate == 0.5
    assert report.expectancy_r == 0.0
    assert report.max_drawdown_r <= 0.0


def test_score_sensitivity_returns_each_threshold() -> None:
    rows = score_sensitivity(
        _prices(),
        thresholds=(0.0, 50.0),
        warmup_sessions=120,
        max_positions=2,
    )
    assert [row["minimum_score"] for row in rows] == [0.0, 50.0]
    assert all("expectancy_r" in row for row in rows)
