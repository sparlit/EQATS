"""
Unit and Integration Tests for ML4T Financial Machine Learning Engine & SEBI Adapter.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from institutional_integrations.ml4t_trading_engine import (
    MAGIC_NUMBER_ML4T,
    EigenportfolioDecomposition,
    ML4TBrokerAdapter,
    ML4TSignalEngine,
    ML4TTradingEngine,
    PurgedWalkForwardCV,
    is_ist_market_open,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_round_tick_005() -> None:
    assert round_tick_005(100.02) == 100.00
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.08) == 100.10
    assert round_tick_005(0.0) == 0.05
    assert round_tick_005(-5.0) == 0.05


def test_is_ist_market_open() -> None:
    # Wednesday 10:30 AM IST (market open)
    open_dt = datetime(2026, 3, 11, 10, 30, 0)
    assert is_ist_market_open(open_dt) is True

    # Sunday (market closed)
    sun_dt = datetime(2026, 3, 15, 10, 30, 0)
    assert is_ist_market_open(sun_dt) is False

    # Wednesday 8:00 AM IST (before market open)
    early_dt = datetime(2026, 3, 11, 8, 0, 0)
    assert is_ist_market_open(early_dt) is False


def test_purged_walk_forward_cv() -> None:
    cv = PurgedWalkForwardCV(train_days=100, val_days=30, embargo_days=5, num_folds=2)
    start_dt = datetime(2026, 1, 1, 0, 0, 0)
    splits = cv.generate_splits(start_dt)
    assert len(splits) == 2
    f1 = splits[0]
    assert f1.fold_index == 1
    assert f1.train_end == start_dt + timedelta(days=100)
    assert f1.embargo_end == f1.train_end + timedelta(days=5)
    assert f1.val_start == f1.embargo_end
    assert f1.val_end == f1.val_start + timedelta(days=30)


def test_eigenportfolio_decomposition() -> None:
    pca_engine = EigenportfolioDecomposition()
    returns_data = {
        "AAPL": [0.01, -0.02, 0.015, 0.005, -0.01, 0.02],
        "MSFT": [0.008, -0.018, 0.012, 0.004, -0.008, 0.018],
        "GOOGL": [0.012, -0.022, 0.018, 0.006, -0.012, 0.022],
    }
    res = pca_engine.compute_eigenportfolios(returns_data, n_components=2)
    assert res.num_components == 2
    assert len(res.explained_variance_ratios) == 2
    assert "AAPL" in res.first_eigenportfolio_weights
    assert "MSFT" in res.first_eigenportfolio_weights
    assert "GOOGL" in res.first_eigenportfolio_weights


def test_ml4t_signal_engine_feature_extraction_and_models() -> None:
    prices = [100.0, 101.5, 102.0, 101.0, 103.5, 104.0, 105.2, 106.0, 105.5, 107.0]
    for m in ["linear", "ridge", "lasso", "random_forest", "gbdt"]:
        sig_engine = ML4TSignalEngine(model_type=m)
        features = sig_engine.compute_technical_features(prices)
        assert "sma_ratio" in features
        assert "rsi" in features
        assert "macd" in features
        assert "volatility" in features
        assert "momentum" in features

        signal = sig_engine.predict_signal(features)
        assert -1.0 <= signal <= 1.0


def test_ml4t_trading_engine_portfolio_allocation_and_metrics() -> None:
    engine = ML4TTradingEngine(initial_capital=1000000.0, model_type="ridge")
    symbol_prices = {
        "RELIANCE": [2400.0, 2420.0, 2450.0, 2430.0, 2460.0, 2480.0, 2500.0],
        "TCS": [3500.0, 3520.0, 3510.0, 3530.0, 3550.0, 3570.0, 3600.0],
        "INFY": [1500.0, 1510.0, 1505.0, 1520.0, 1530.0, 1540.0, 1550.0],
    }

    weights = engine.allocate_portfolio(symbol_prices)
    assert "RELIANCE" in weights
    assert "TCS" in weights
    assert "INFY" in weights
    assert round(sum(weights.values()), 2) == 1.0

    history = [1000000.0, 1010000.0, 1005000.0, 1020000.0, 1030000.0, 1025000.0, 1040000.0]
    metrics = engine.calculate_backtest_metrics(history)
    assert metrics["cumulative_return"] == 0.04
    assert metrics["sharpe_ratio"] > 0
    assert metrics["max_drawdown"] >= 0

    order_rec = engine.generate_order_recommendation(
        symbol="RELIANCE", target_weight=0.4, current_price=2500.0
    )
    assert order_rec["symbol"] == "RELIANCE"
    assert order_rec["action"] == "BUY"
    assert order_rec["quantity"] == 160
    assert order_rec["magic_number"] == MAGIC_NUMBER_ML4T


def test_ml4t_broker_adapter_and_registry() -> None:
    # Check registration in IndianBrokerPluginRegistry
    reg_cls = IndianBrokerPluginRegistry.get_adapter_class("ML4T")
    assert reg_cls == ML4TBrokerAdapter

    reg_cls_alt = IndianBrokerPluginRegistry.get_adapter_class("MACHINE_LEARNING_FOR_TRADING")
    assert reg_cls_alt == ML4TBrokerAdapter

    adapter = ML4TBrokerAdapter()
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    acc_info = adapter.get_account_info()
    assert acc_info["broker"] == "ML4TBroker"
    assert acc_info["magic_number"] == MAGIC_NUMBER_ML4T

    price_info = adapter.get_current_price("RELIANCE")
    assert price_info["last_price"] == 100.0

    # Order execution with IST open
    req = SEBIOrderRequest(
        symbol="RELIANCE",
        quantity=10,
        order_type="LIMIT",
        price=2500.0,
        product="CNC",
        exchange="NSE",
    )

    with patch("institutional_integrations.ml4t_trading_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success is True
        assert res.status == "FILLED"
        assert res.instrument_token == MAGIC_NUMBER_ML4T

    # Order execution with IST closed
    with patch("institutional_integrations.ml4t_trading_engine.is_ist_market_open", return_value=False):
        res_closed = adapter.execute_order(req)
        assert res_closed.success is False
        assert res_closed.status == "REJECTED"
        assert "Outside IST trading hours" in res_closed.error

    close_res = adapter.close_order("ML4T-12345")
    assert close_res.success is True
    assert close_res.status == "CANCELLED"

    assert adapter.disconnect() is True
    assert adapter.is_connected() is False
