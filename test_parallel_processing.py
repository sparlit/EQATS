"""
Unit test suite verifying parallel processing and batch worker performance.
"""

import pytest
from predictive_brain import batch_predict_symbols_parallel
from institutional_integrations.backtest_engine import EventDrivenBacktester

def test_batch_predict_symbols_parallel():
    """Verify concurrent multi-symbol neural network predictions."""
    inputs_map = {
        "EURUSD": [0.5, 1.01, 0.0002, 0.001, 1.0, 1.2],
        "GBPUSD": [0.4, 0.99, -0.0001, -0.0005, 0.0, 0.9],
        "USDJPY": [0.6, 1.03, 0.0005, 0.002, 1.0, 1.5],
        "XAUUSD": [0.35, 0.98, -0.0004, -0.001, 0.0, 0.8]
    }
    results = batch_predict_symbols_parallel(inputs_map)
    assert len(results) == 4
    for sym in inputs_map:
        assert sym in results
        assert 0.0 <= results[sym] <= 1.0

def test_parallel_walk_forward_optimization():
    """Verify parallel backtest parameter grid search."""
    # Generate dummy historical bars
    bars = []
    p = 1.1000
    for i in range(100):
        p += (0.0005 if i % 2 == 0 else -0.0004)
        bars.append({"open": p, "high": p + 0.0002, "low": p - 0.0002, "close": p})

    backtester = EventDrivenBacktester(initial_capital=10000.0)
    grid = [(10, 20), (15, 30), (20, 40), (25, 50)]
    wf_res = backtester.walk_forward_optimization(bars, param_grid=grid)

    assert "best_params_sl_tp" in wf_res
    assert wf_res["best_params_sl_tp"] in grid
    assert "best_sharpe" in wf_res
