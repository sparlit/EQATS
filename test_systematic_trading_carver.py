"""
Unit and Integration Tests for PySystemTrade Carver Systematic Trading Engine.
"""

import pytest

from institutional_integrations.systematic_trading_carver import (
    PySystemTradeEngine,
)


def test_carver_diversification_multiplier():
    engine = PySystemTradeEngine()

    weights = {"AAPL": 0.5, "MSFT": 0.5}
    corr_low = [[1.0, 0.1], [0.1, 1.0]]  # Low correlation

    res = engine.calculate_diversification_multiplier(weights, corr_low)
    assert res.diversification_multiplier > 1.0
    assert res.portfolio_variance > 0.0


def test_carver_shrinkage_correlation_matrix():
    engine = PySystemTradeEngine()

    corr_raw = [[1.0, 0.8], [0.8, 1.0]]
    shrunk = engine.shrink_correlation_matrix(corr_raw, shrinkage_factor=0.5)

    assert shrunk[0][0] == 1.0
    assert shrunk[0][1] == 0.8  # Avg of off-diagonal is 0.8, so 0.5*0.8 + 0.5*0.8 = 0.8


def test_carver_scale_forecast_signal():
    engine = PySystemTradeEngine()

    raw_signals = [1.0, -0.5, 0.2, 0.8, -1.5]
    scaled_res = engine.scale_forecast_signal(raw_signals, target_average_abs_forecast=10.0)

    assert scaled_res.scaling_factor > 1.0
    assert len(scaled_res.scaled_forecasts) == 5
    assert all(-20.0 <= f <= 20.0 for f in scaled_res.scaled_forecasts)
