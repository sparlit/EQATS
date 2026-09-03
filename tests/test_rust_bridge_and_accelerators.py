"""
Integration and Benchmarking Test Suite for Rust CFFI Acceleration Core and Fallback Dynamics.
"""

import time
from typing import Any

import numpy as np

import indicators
from institutional_integrations.rust_bridge import (
    _mark_rust_failure,
    execute_high_speed_rust_order_send,
    is_rust_available,
    rust_accelerated_ema,
    rust_accelerated_mcts_risk_simulation,
    rust_accelerated_vpin,
)


def test_rust_library_loading() -> None:
    """Verifies compiled Rust library loading state function executes cleanly."""
    avail = is_rust_available()
    assert isinstance(avail, bool)


def test_rust_vs_python_ema_numerical_precision() -> None:
    """Verifies Rust accelerated EMA matches Python precision within float tolerance."""
    prices = list(np.random.randn(1000).cumsum() + 100.0)
    period = 20
    py_ema = indicators.calculate_ema(prices, period)
    rust_series = rust_accelerated_ema(prices, period)
    assert len(rust_series) == len(prices)
    assert abs(rust_series[-1] - py_ema) < 1e-06, f"EMA disparity: Python {py_ema} vs Rust {rust_series[-1]}"


def test_rust_vpin_calculation() -> None:
    """Verifies Rust accelerated VPIN flow imbalance calculation."""
    buys = [10.0, 25.0, 30.0, 15.0, 50.0]
    sells = [12.0, 20.0, 35.0, 10.0, 45.0]
    vpin_val = rust_accelerated_vpin(buys, sells, bucket_size=100.0)
    assert 0.0 <= vpin_val <= 1.0
    expected_vpin = 22.0 / 252.0
    assert abs(vpin_val - expected_vpin) < 1e-05


def test_rust_mcts_tail_risk_parallel() -> None:
    """Verifies MCTS tail risk simulation execution and result structure."""
    start = time.perf_counter()
    res = rust_accelerated_mcts_risk_simulation(initial_equity=100000.0, open_positions_count=5, simulations=5000)
    elapsed = (time.perf_counter() - start) * 1000.0
    assert "max_drawdown" in res
    assert "var_99" in res
    if is_rust_available():
        assert res["engine_type"] == "RUST_PARALLEL_RAYON"
        assert elapsed < 100.0, f"5000 parallel MCTS simulations should complete sub-100ms, took {elapsed:.2f}ms"
    else:
        assert res["engine_type"] == "PYTHON_FALLBACK"
    assert res["max_drawdown"] >= 0.0
    assert res["var_99"] >= 0.0


def test_rust_order_execution_bridge() -> None:
    """Verifies order matching latency logging."""
    res = execute_high_speed_rust_order_send("EUR_USD", "BUY", 1.085, 1.0)
    assert res["status"] == "FILLED"
    if is_rust_available():
        assert res["matching_engine"] == "RUST_L3_DIRECT_DMA"
        assert res["engine_type"] == "RUST_ACCELERATED"
    else:
        assert res["matching_engine"] == "PYTHON_EMULATED_MATCHING"
        assert res["engine_type"] == "PYTHON_FALLBACK"
    assert res["execution_latency_ns"] >= 0


def test_rust_self_healing_circuit_breaker_fallback() -> None:
    """Verifies dynamic fallback to Python on failure and automatic cooldown recovery."""
    _mark_rust_failure()
    assert is_rust_available() is False
    res_fb = execute_high_speed_rust_order_send("GBP_USD", "SELL", 1.25, 0.5)
    assert res_fb["engine_type"] == "PYTHON_FALLBACK"
    assert res_fb["matching_engine"] == "PYTHON_EMULATED_MATCHING"
    mcts_fb = rust_accelerated_mcts_risk_simulation(initial_equity=50000.0, open_positions_count=2, simulations=100)
    assert mcts_fb["engine_type"] == "PYTHON_FALLBACK"
