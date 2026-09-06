"""
Tests for AI Stock Live Trader Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.ai_stock_live_trader_engine import (
    AIStockLiveTraderEngine,
    AIStockLiveTraderBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_AI_STOCK_LIVE_TRADER,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_heikin_ashi_and_gmma_evaluations():
    engine = AIStockLiveTraderEngine()
    assert engine.magic_number == MAGIC_NUMBER_AI_STOCK_LIVE_TRADER

    opens = [100.0, 102.0, 104.0, 103.0]
    highs = [103.0, 105.0, 106.0, 105.0]
    lows = [99.0, 101.0, 102.0, 101.0]
    closes = [102.0, 104.0, 103.0, 104.5]

    ha_res = engine.convert_to_heikin_ashi(opens, highs, lows, closes)
    assert len(ha_res["ha_close"]) == 4
    assert ha_res["ha_close"][0] == 101.0  # (100+103+99+102)/4

    prices = [100.0 + i * 0.5 for i in range(100)]
    gmma_res = engine.evaluate_gmma_trend(prices)
    assert gmma_res["gmma_score"] > 0.0
    assert gmma_res["trend_status"] in ("BULLISH", "STRONG_BULLISH")


def test_ai_stock_live_trader_broker_adapter():
    adapter = AIStockLiveTraderBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("AI_STOCK_LIVE_TRADER") == AIStockLiveTraderBrokerAdapter

    req = SEBIOrderRequest(
        symbol="TATAMOTORS",
        quantity=10,
        price=980.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.ai_stock_live_trader_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 980.00
        assert res.ticket.startswith("AILIVE-")
