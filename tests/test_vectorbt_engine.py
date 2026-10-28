"""
Unit tests for VectorBT Engine and Broker Adapter Plugin.
"""

from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pytest

from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)
from institutional_integrations.vectorbt_engine import (
    MAGIC_NUMBER_VECTORBT,
    VectorBTBrokerAdapter,
    VectorBTEngine,
    is_ist_market_open,
    round_tick_005,
)


def test_round_tick_005() -> None:
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.02) == 100.00
    assert round_tick_005(100.07) == 100.05
    assert round_tick_005(100.08) == 100.10
    assert round_tick_005(-10.0) == 0.05
    assert round_tick_005(float("nan")) == 0.05


def test_is_ist_market_open() -> None:
    # Monday 10:00 AM IST -> Market Open
    dt_open = datetime(2025, 3, 10, 10, 0, 0, tzinfo=timezone.utc)
    # Sunday 10:00 AM IST -> Market Closed
    dt_weekend = datetime(2025, 3, 9, 10, 0, 0, tzinfo=timezone.utc)
    # Monday 08:00 AM IST -> Market Closed
    dt_early = datetime(2025, 3, 10, 2, 30, 0, tzinfo=timezone.utc)

    assert is_ist_market_open(dt_open) is True
    assert is_ist_market_open(dt_weekend) is False
    assert is_ist_market_open(dt_early) is False


def test_vectorbt_engine_initialization() -> None:
    engine = VectorBTEngine(initial_capital=500000.0, fees=0.001, slippage=0.0002)
    assert engine.initial_capital == 500000.0
    assert engine.fees == 0.001
    assert engine.slippage == 0.0002
    assert engine.magic_number == MAGIC_NUMBER_VECTORBT


def test_generate_ma_crossover_signals() -> None:
    engine = VectorBTEngine()
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    prices = pd.Series(np.linspace(100, 200, 100), index=dates)

    entries, exits = engine.generate_ma_crossover_signals(prices, fast_window=5, slow_window=20)
    assert isinstance(entries, (pd.Series, pd.DataFrame))
    assert isinstance(exits, (pd.Series, pd.DataFrame))
    assert len(entries) == 100
    assert len(exits) == 100


def test_generate_rsi_signals() -> None:
    engine = VectorBTEngine()
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    np.random.seed(42)
    price_vals = 100 + np.cumsum(np.random.randn(100))
    prices = pd.Series(price_vals, index=dates)

    entries, exits = engine.generate_rsi_signals(prices, window=14, lower_th=30, upper_th=70)
    assert isinstance(entries, (pd.Series, pd.DataFrame))
    assert isinstance(exits, (pd.Series, pd.DataFrame))
    assert len(entries) == 100


def test_generate_bollinger_signals() -> None:
    engine = VectorBTEngine()
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    np.random.seed(42)
    price_vals = 100 + np.cumsum(np.random.randn(100))
    prices = pd.Series(price_vals, index=dates)

    entries, exits = engine.generate_bollinger_signals(prices, window=20, alpha=2.0)
    assert isinstance(entries, (pd.Series, pd.DataFrame))
    assert isinstance(exits, (pd.Series, pd.DataFrame))
    assert len(entries) == 100


def test_run_vectorized_backtest() -> None:
    engine = VectorBTEngine(initial_capital=1000000.0)
    dates = pd.date_range("2025-01-01", periods=100, freq="D")
    np.random.seed(42)
    price_vals = 100 + np.cumsum(np.random.randn(100))
    prices = pd.Series(price_vals, index=dates)

    entries, exits = engine.generate_ma_crossover_signals(prices, fast_window=5, slow_window=20)
    results = engine.run_vectorized_backtest(prices, entries, exits)

    assert "total_return" in results
    assert "sharpe_ratio" in results
    assert "max_drawdown" in results
    assert "total_trades" in results
    assert "win_rate" in results
    assert "portfolio_value" in results


def test_grid_search_ma_crossover() -> None:
    engine = VectorBTEngine()
    dates = pd.date_range("2025-01-01", periods=50, freq="D")
    prices = pd.Series(np.linspace(100, 150, 50), index=dates)

    grid_res = engine.grid_search_ma_crossover(prices, fast_windows=[5, 10], slow_windows=[15, 20])
    assert "best_params" in grid_res
    assert "grid_results" in grid_res
    assert grid_res["total_combinations"] == 4


def test_calculate_portfolio_metrics() -> None:
    engine = VectorBTEngine()
    history = [1000000.0, 1010000.0, 1025000.0, 1015000.0, 1040000.0]
    metrics = engine.calculate_portfolio_metrics(history)

    assert metrics["total_return"] > 0
    assert "sharpe_ratio" in metrics
    assert "max_drawdown" in metrics
    assert "profit_factor" in metrics


def test_generate_order_recommendation() -> None:
    engine = VectorBTEngine(initial_capital=1000000.0)
    rec_buy = engine.generate_order_recommendation("RELIANCE", entry_signal=True, exit_signal=False, current_price=2500.0)
    assert rec_buy["action"] == "BUY"
    assert rec_buy["quantity"] > 0
    assert rec_buy["magic_number"] == MAGIC_NUMBER_VECTORBT

    rec_sell = engine.generate_order_recommendation("RELIANCE", entry_signal=False, exit_signal=True, current_price=2500.0)
    assert rec_sell["action"] == "SELL"
    assert rec_sell["quantity"] == 0


def test_vectorbt_broker_adapter() -> None:
    adapter = VectorBTBrokerAdapter()
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    info = adapter.get_account_info()
    assert info["broker"] == "VectorBTBroker"
    assert info["magic_number"] == MAGIC_NUMBER_VECTORBT

    # Test IndianBrokerPluginRegistry lookup
    adapter_cls = IndianBrokerPluginRegistry.get_adapter_class("VECTORBT")
    assert adapter_cls is VectorBTBrokerAdapter

    # Test order execution during simulated market open
    req = SEBIOrderRequest(
        symbol="TCS",
        quantity=10,
        price=3500.02,
        order_type="BUY",
        order_kind="LIMIT",
        product="CNC",
        exchange="NSE",
    )

    # Mock market session open for deterministic order execution
    dt_open = datetime(2025, 3, 10, 10, 0, 0, tzinfo=timezone.utc)
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("institutional_integrations.vectorbt_engine.is_ist_market_open", lambda: True)
        res = adapter.execute_order(req)
        assert res.success is True
        assert res.status == "FILLED"
        assert res.price == 3500.00
        assert res.instrument_token == MAGIC_NUMBER_VECTORBT

    assert adapter.modify_order("TICKET123") is True
    close_res = adapter.close_order("TICKET123")
    assert close_res.status == "CANCELLED"
    assert adapter.disconnect() is True
