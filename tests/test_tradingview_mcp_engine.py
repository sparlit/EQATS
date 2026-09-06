"""
Tests for TradingView MCP Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.tradingview_mcp_engine import (
    TradingViewMCPEngine,
    TradingViewMCPBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_TRADINGVIEW_MCP,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_technical_summary_recommendation():
    engine = TradingViewMCPEngine()
    assert engine.magic_number == MAGIC_NUMBER_TRADINGVIEW_MCP

    prices = [100.0 + i * 0.5 for i in range(30)]
    summary = engine.compute_technical_summary(prices)
    assert summary["recommendation"] in ("BUY", "STRONG_BUY")
    assert summary["symbol_price"] == 114.50


def test_tradingview_mcp_broker_adapter():
    adapter = TradingViewMCPBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("TRADINGVIEW_MCP") == TradingViewMCPBrokerAdapter

    req = SEBIOrderRequest(
        symbol="SBIN",
        quantity=50,
        price=820.02,
        order_type="BUY",
        product="MIS",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.tradingview_mcp_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 820.00
        assert res.ticket.startswith("TVMCP-")
