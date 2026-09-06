"""
Tests for Live NSE Stock Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.live_nse_stock_engine import (
    LiveNSEStockEngine,
    LiveNSEStockBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_LIVE_NSE_STOCK,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_quote_response_parsing():
    engine = LiveNSEStockEngine()
    assert engine.magic_number == MAGIC_NUMBER_LIVE_NSE_STOCK

    raw = {
        "symbol": "INFY",
        "lastPrice": "1850.02",
        "previousClose": "1800.00",
        "pChange": "2.78",
        "totalTradedVolume": "1500000",
    }

    parsed = engine.parse_quote_response(raw)
    assert parsed["symbol"] == "INFY"
    assert parsed["last_price"] == 1850.00
    assert parsed["prev_close"] == 1800.00
    assert parsed["p_change"] == 2.78
    assert parsed["volume"] == 1500000


def test_live_nse_stock_broker_adapter():
    adapter = LiveNSEStockBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("LIVE_NSE_STOCK") == LiveNSEStockBrokerAdapter

    req = SEBIOrderRequest(
        symbol="INFY",
        quantity=15,
        price=1850.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.live_nse_stock_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 1850.00
        assert res.ticket.startswith("LNS-")
