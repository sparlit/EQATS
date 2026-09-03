"""
Unit tests for Backtesting.py Suite integration.
Verifies crossover, cross, barssince, resample_apply, SignalStrategy, and TrailingStrategy.
"""

from typing import Any

import numpy as np
import pandas as pd
import pytest

from institutional_integrations.backtesting_py_suite import (
    SignalStrategy,
    TrailingStrategy,
    barssince,
    cross,
    crossover,
    resample_apply,
)


def test_signal_math_helpers() -> None:
    s1 = [10, 12, 15, 20]
    s2 = [11, 13, 16, 18]
    assert crossover(s1, s2) is True
    assert cross(s1, s2) is True
    cond = [False, True, False, False, True, False, False]
    assert barssince(cond) == 2


def test_resample_apply() -> Any:
    dates = pd.date_range("2025-01-01", periods=100, freq="1h")
    prices = pd.Series(np.linspace(100, 110, 100), index=dates)

    def simple_sma(s: Any, window: Any = 5) -> Any:
        return s.rolling(window).mean()

    aligned_sma = resample_apply("4h", simple_sma, prices, window=3)
    assert len(aligned_sma) == 100
    assert not aligned_sma.isna().all()


def test_signal_strategy() -> None:
    strat = SignalStrategy(entry_signal_threshold=0.5)
    buy_sig = strat.evaluate_signal(current_price=100.0, signal_value=0.8, atr=2.0)
    assert buy_sig.direction == "BUY"
    assert buy_sig.stop_loss == 96.0
    assert buy_sig.take_profit == 108.0
    sell_sig = strat.evaluate_signal(current_price=100.0, signal_value=-0.8, atr=2.0)
    assert sell_sig.direction == "SELL"
    assert sell_sig.stop_loss == 104.0
    assert sell_sig.take_profit == 92.0
    close_sig = strat.evaluate_signal(current_price=100.0, signal_value=0.0)
    assert close_sig.direction == "CLOSE"


def test_trailing_strategy() -> None:
    ts = TrailingStrategy(n_atr=2.0)
    sl = ts.update_trailing_stop(
        position_type="BUY", current_price=105.0, extreme_price=110.0, current_sl=100.0, atr=2.0,
    )
    assert sl == 106.0
    ts_pct = TrailingStrategy(pct_trail=0.05)
    sl_sell = ts_pct.update_trailing_stop(
        position_type="SELL", current_price=95.0, extreme_price=90.0, current_sl=100.0,
    )
    assert sl_sell == 94.5
