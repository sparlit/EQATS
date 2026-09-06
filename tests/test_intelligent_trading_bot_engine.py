"""
Tests for Intelligent Trading Bot ML Feature Engineering Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.intelligent_trading_bot_engine import (
    IntelligentTradingBotEngine,
    IntelligentTradingBotBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_INTELLIGENT_TRADING_BOT,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_feature_generation_and_ml_signal():
    engine = IntelligentTradingBotEngine(horizon_bars=60)
    assert engine.magic_number == MAGIC_NUMBER_INTELLIGENT_TRADING_BOT

    prices = [100.0, 101.0, 102.5, 101.8, 103.0, 104.2, 105.0]
    highs = [100.5, 101.5, 103.0, 102.2, 103.5, 104.8, 105.5]
    lows = [99.5, 100.2, 101.0, 101.0, 102.0, 103.5, 104.2]

    features = engine.compute_rolling_features(prices, highs, lows)
    assert features["ret_mean"] > 0.0
    assert features["volatility"] > 0.0
    assert features["high_ratio"] >= 0.0

    eval_res = engine.evaluate_ml_signal(features, close_price=105.02)
    assert eval_res["price"] == 105.00
    assert eval_res["prob_buy"] > 0.5
    assert eval_res["recommended_signal"] == "BUY"


def test_intelligent_trading_bot_broker_adapter():
    adapter = IntelligentTradingBotBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("INTELLIGENT_TRADING_BOT") == IntelligentTradingBotBrokerAdapter

    req = SEBIOrderRequest(
        symbol="RELIANCE",
        quantity=10,
        price=2500.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.intelligent_trading_bot_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 2500.00
        assert res.ticket.startswith("ITBOT-")
