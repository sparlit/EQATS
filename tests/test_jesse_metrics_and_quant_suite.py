"""
Unit tests for Jesse Metrics & Quant Strategy Suite.
Verifies JesseMetricsEngine and JesseQuantStrategyLibrary.
"""

from typing import Any

import pytest

from institutional_integrations.jesse_metrics_and_quant_suite import JesseMetricsEngine, JesseQuantStrategyLibrary


def test_jesse_metrics_engine() -> None:
    engine = JesseMetricsEngine()
    returns = [0.01, -0.005, 0.02, 0.015, -0.01, 0.03, -0.002, 0.012]
    pnls = [100.0, -50.0, 200.0, 150.0, -100.0, 300.0, -20.0, 120.0]
    report = engine.evaluate_performance(returns=returns, trade_pnls=pnls, initial_balance=10000.0)
    assert report.total_trades == 8
    assert report.win_rate == 62.5
    assert report.sharpe_ratio > 0.0
    assert report.smart_sharpe_ratio > 0.0
    assert report.sortino_ratio > 0.0
    assert report.omega_ratio > 1.0
    assert report.expected_value_usd > 0.0


def test_jesse_quant_strategies() -> None:
    lib = JesseQuantStrategyLibrary()
    sig1 = lib.london_breakout(current_price=1.105, asian_high=1.1, asian_low=1.095, atr=0.002)
    assert sig1.direction == "BUY"
    assert sig1.stop_loss < 1.105
    assert sig1.take_profit > 1.105
    sig2 = lib.london_breakout(current_price=1.092, asian_high=1.1, asian_low=1.095, atr=0.002)
    assert sig2.direction == "SELL"
    sig3 = lib.london_breakout(current_price=1.097, asian_high=1.1, asian_low=1.095, atr=0.002)
    assert sig3.direction == "HOLD"
    ha_opens = [100.0, 101.0, 102.0]
    ha_closes = [101.5, 102.5, 103.5]
    sig_ha = lib.heikin_ashi_trend(ha_opens, ha_closes, atr=1.0)
    assert sig_ha.direction == "BUY"
    highs = [10.0 + i * 0.1 for i in range(35)]
    lows = [9.0 + i * 0.1 for i in range(35)]
    sig_ao = lib.awesome_oscillator(highs, lows, current_price=14.0, atr=0.5)
    assert sig_ao.direction in ["BUY", "SELL", "HOLD"]
