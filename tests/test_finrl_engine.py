"""
Tests for FinRL Framework Engine Integration Module
"""

from unittest.mock import patch

import pytest
from institutional_integrations.finrl_engine import (
    MAGIC_NUMBER_FINRL,
    FinRLBrokerAdapter,
    FinRLFrameworkEngine,
    is_ist_market_open,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_round_tick_005():
    assert round_tick_005(100.02) == 100.0
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.07) == 100.05
    assert round_tick_005(100.08) == 100.10
    assert round_tick_005(-5.0) == 0.05
    assert round_tick_005(float("nan")) == 0.05


def test_finrl_engine_initialization():
    engine = FinRLFrameworkEngine(initial_capital=500000.0, algorithm="ppo")
    assert engine.initial_capital == 500000.0
    assert engine.algorithm == "ppo"
    assert engine.magic_number == MAGIC_NUMBER_FINRL


def test_finrl_engine_extract_indicators():
    engine = FinRLFrameworkEngine()
    data = {
        "close": 1500.0,
        "high": 1520.0,
        "low": 1490.0,
        "open": 1495.0,
        "volume": 25000.0,
        "sma_20": 1480.0,
        "sma_50": 1450.0,
        "rsi": 62.5,
        "macd": 12.4,
        "adx": 28.0,
        "turbulence": 1.2,
    }
    extracted = engine.extract_technical_indicators("RELIANCE", data)
    assert extracted["symbol"] == "RELIANCE"
    assert extracted["close"] == 1500.0
    assert extracted["sma_20"] == 1480.0
    assert extracted["rsi"] == 62.5


def test_finrl_predict_drl_actions_algorithms():
    state = {
        "RELIANCE": {"close": 1500.0, "sma_20": 1480.0, "sma_50": 1450.0, "rsi": 60.0, "macd": 5.0, "adx": 25.0, "turbulence": 1.0},
        "TCS": {"close": 3200.0, "sma_20": 3250.0, "sma_50": 3300.0, "rsi": 40.0, "macd": -2.0, "adx": 15.0, "turbulence": 1.5},
    }

    for algo in ["ppo", "a2c", "ddpg", "sac", "td3", "ensemble"]:
        engine = FinRLFrameworkEngine(algorithm=algo)
        weights = engine.predict_drl_actions(state)
        assert len(weights) == 2
        assert abs(sum(weights.values()) - 1.0) < 1e-4
        assert "RELIANCE" in weights and "TCS" in weights


def test_finrl_backtest_metrics():
    engine = FinRLFrameworkEngine()
    history = [1000000.0, 1010000.0, 1025000.0, 1015000.0, 1040000.0]
    metrics = engine.calculate_backtest_metrics(history)

    assert "cumulative_return" in metrics
    assert "sharpe_ratio" in metrics
    assert "max_drawdown" in metrics
    assert metrics["cumulative_return"] == 0.04
    assert metrics["max_drawdown"] >= 0.0


def test_finrl_order_recommendation():
    engine = FinRLFrameworkEngine(initial_capital=1000000.0, algorithm="ensemble")
    rec = engine.generate_order_recommendation("INFY", 0.5, 1500.0)

    assert rec["symbol"] == "INFY"
    assert rec["action"] == "BUY"
    assert rec["quantity"] > 0
    assert rec["price"] == 1500.0
    assert rec["magic_number"] == MAGIC_NUMBER_FINRL


def test_finrl_broker_adapter_registry_and_order():
    adapter_cls = IndianBrokerPluginRegistry.get_adapter_class("FINRL")
    assert adapter_cls == FinRLBrokerAdapter

    adapter = FinRLBrokerAdapter()
    assert adapter.connect()
    assert adapter.is_connected()

    account = adapter.get_account_info()
    assert account["broker"] == "FinRLBroker"
    assert account["magic_number"] == MAGIC_NUMBER_FINRL

    # Test order execution when IST market is open
    req = SEBIOrderRequest(
        symbol="TATASTEEL",
        order_type="BUY",
        quantity=50,
        price=120.0,
        product="CNC",
        exchange="NSE",
    )

    with patch("institutional_integrations.finrl_engine.is_ist_market_open", return_value=True):
        resp = adapter.execute_order(req)
        assert resp.success is True
        assert resp.status == "FILLED"
        assert resp.ticket.startswith("FINRL-")
        assert resp.price == 120.0

    # Test order rejection when IST market is closed
    with patch("institutional_integrations.finrl_engine.is_ist_market_open", return_value=False):
        resp_closed = adapter.execute_order(req)
        assert resp_closed.success is False
        assert resp_closed.status == "REJECTED"
