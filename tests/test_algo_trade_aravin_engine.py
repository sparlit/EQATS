"""
Tests for Algo-Trade Multi-Broker Engine Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.algo_trade_aravin_engine import (
    AlgoTradeAravinEngine,
    AlgoTradeAravinBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_ALGO_TRADE_ARAVIN,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_multi_broker_router_and_session_refresh():
    engine = AlgoTradeAravinEngine()
    assert engine.magic_number == MAGIC_NUMBER_ALGO_TRADE_ARAVIN

    # Session refresh
    ref_res = engine.refresh_broker_session("UPSTOX", "test_token_abc")
    assert ref_res["status"] == "SESSION_ACTIVE"

    # Order routing with active session
    order_res = engine.route_order_execution(
        target_broker="UPSTOX",
        request_data={"symbol": "INFY", "price": 1500.02, "quantity": 10},
    )
    assert order_res["success"]
    assert order_res["broker"] == "UPSTOX"
    assert order_res["price"] == 1500.00

    # Order routing with inactive session
    inactive_res = engine.route_order_execution(
        target_broker="ZERODHA",
        request_data={"symbol": "INFY", "price": 1500.00, "quantity": 10},
    )
    assert not inactive_res["success"]
    assert "SESSION_INACTIVE" in inactive_res["error"]


def test_algo_trade_aravin_broker_adapter():
    adapter = AlgoTradeAravinBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("ALGO_TRADE_ARAVIN") == AlgoTradeAravinBrokerAdapter

    req = SEBIOrderRequest(
        symbol="TCS",
        quantity=5,
        price=3600.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.algo_trade_aravin_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 3600.00
        assert res.ticket.startswith("ALGOTRADE-")
