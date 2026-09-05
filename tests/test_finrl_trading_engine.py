"""
Tests for FinRL Trading Engine Integration Module
"""

import pytest
from datetime import datetime
from unittest.mock import patch

from institutional_integrations.finrl_trading_engine import (
    FinRLTradingEngine,
    FinRLTradingBrokerAdapter,
    round_tick_005,
    is_ist_market_open,
    MAGIC_NUMBER_FINRL_TRADING,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_round_tick_005():
    assert round_tick_005(100.02) == 100.0
    assert round_tick_005(100.03) == 100.05
    assert round_tick_005(100.08) == 100.10


def test_finrl_engine_allocation():
    engine = FinRLTradingEngine(initial_capital=500000.0)
    assert engine.magic_number == MAGIC_NUMBER_FINRL_TRADING

    features = {
        "RELIANCE": {"close": 2500.0, "sma_50": 2400.0, "sma_200": 2200.0, "rsi": 58.0, "momentum_3m": 0.15},
        "TCS": {"close": 3500.0, "sma_50": 3600.0, "sma_200": 3700.0, "rsi": 40.0, "momentum_3m": -0.05},
    }

    weights = engine.evaluate_drl_portfolio_weights(features)
    assert "RELIANCE" in weights
    assert "TCS" in weights
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["RELIANCE"] > weights["TCS"]

    alloc = engine.execute_allocation("RELIANCE", weights["RELIANCE"], 2500.0, 500000.0)
    assert alloc["symbol"] == "RELIANCE"
    assert alloc["action"] == "BUY"
    assert alloc["quantity"] > 0
    assert alloc["magic_number"] == MAGIC_NUMBER_FINRL_TRADING


def test_finrl_broker_adapter():
    adapter = FinRLTradingBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("FINRL_TRADING") == FinRLTradingBrokerAdapter

    req = SEBIOrderRequest(
        symbol="INFY",
        quantity=10,
        price=1500.0,
        order_type="BUY",
        product="MIS",
        exchange="NSE",
        order_kind="LIMIT",
    )

    # Not authenticated rejection
    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success
    assert "not connected" in res_unauth.error

    adapter.connect()

    with patch("institutional_integrations.finrl_trading_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 1500.0
        assert res.ticket.startswith("FINRL-")
