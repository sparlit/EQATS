"""
Test Suite for TradingOS Quantitative Statistics Utilities (quant_stats.py).
Tests Bollinger Bands, crossover signals, RSI, volatility, daily pivots, and numerical stability.
"""

from utils.quant_stats import (
    calculate_bollinger_bands,
    calculate_daily_pivots,
    calculate_realized_volatility,
    calculate_rsi,
    calculate_standard_deviation,
    evaluate_bollinger_signals,
)


def test_calculate_standard_deviation():
    """Tests standard deviation calculation with normal and edge inputs."""
    assert calculate_standard_deviation([]) == 0.0
    assert calculate_standard_deviation([10.0]) == 0.0
    assert calculate_standard_deviation([10.0, 10.0, 10.0]) == 0.0

    vals = [10.0, 12.0, 23.0, 23.0, 16.0, 23.0, 21.0, 16.0]
    std = calculate_standard_deviation(vals)
    assert std > 0.0
    assert round(std, 2) == 4.90


def test_calculate_bollinger_bands():
    """Tests Bollinger Bands calculation and edge cases."""
    assert calculate_bollinger_bands([]) is None
    assert calculate_bollinger_bands([10.0] * 5, period=20) is None

    prices = [100.0 + i * 0.5 for i in range(25)]
    bb = calculate_bollinger_bands(prices, period=20, num_std=2.0)
    assert bb is not None
    assert "upper" in bb
    assert "middle" in bb
    assert "lower" in bb
    assert bb["upper"] > bb["middle"] > bb["lower"]
    assert bb["bandwidth"] > 0.0


def test_evaluate_bollinger_signals():
    """Tests Bollinger Bands crossover signals and extreme conditions."""
    prices = [100.0] * 20
    res = evaluate_bollinger_signals(prices)
    assert res["signal"] == "NEUTRAL"

    # Price drop below lower band and cross above
    prices_cross = [100.0] * 18 + [90.0, 96.0]
    res_cross = evaluate_bollinger_signals(prices_cross)
    assert isinstance(res_cross["signal"], str)


def test_calculate_rsi():
    """Tests RSI calculations with various price series."""
    assert calculate_rsi([]) == 50.0
    assert calculate_rsi([10.0] * 5) == 50.0

    # Strictly increasing prices
    prices_up = [10.0 + i for i in range(20)]
    rsi_up = calculate_rsi(prices_up, period=14)
    assert rsi_up == 100.0

    # Strictly decreasing prices
    prices_down = [100.0 - i for i in range(20)]
    rsi_down = calculate_rsi(prices_down, period=14)
    assert rsi_down == 0.0


def test_calculate_realized_volatility():
    """Tests realized volatility calculation."""
    assert calculate_realized_volatility([]) == 0.0
    assert calculate_realized_volatility([100.0]) == 0.0

    prices = [100.0, 101.5, 99.8, 102.1, 100.4, 103.0]
    vol = calculate_realized_volatility(prices, annualize=False)
    assert vol > 0.0


def test_calculate_daily_pivots():
    """Tests classic Floor Pivot calculations."""
    pivots = calculate_daily_pivots(high=105.0, low=95.0, close=100.0)
    assert pivots["pivot"] == 100.0
    assert pivots["r1"] == 105.0
    assert pivots["s1"] == 95.0
    assert pivots["r2"] == 110.0
    assert pivots["s2"] == 90.0
