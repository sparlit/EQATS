"""
Unit tests for XCryptoEngine and XCryptoBrokerAdapter (Repo 083 Adaptation, Magic 9100080)
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from institutional_integrations.xcrypto_engine import (
    XCryptoEngine,
    XCryptoBrokerAdapter,
    MAGIC_NUMBER,
    round_tick_005,
    is_ist_market_open,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    SEBIOrderResponse,
)


def test_xcrypto_engine_pyalgo_signals():
    engine = XCryptoEngine()
    prices = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0,
              110.0, 111.0, 112.0, 113.0, 114.0, 115.0, 116.0, 117.0, 118.0, 119.0, 125.0]
    res = engine.evaluate_pyalgo_signal("BTCUSDT", prices, short_window=3, long_window=10)
    assert res["symbol"] == "BTCUSDT"
    assert res["action"] in ["BUY", "SELL", "HOLD"]


def test_xcrypto_engine_order_and_position():
    engine = XCryptoEngine()
    order = engine.place_order(
        symbol="BTCUSDT",
        side="BUY",
        quantity=2.0,
        price=50000.03,
        order_type="LIMIT",
        leverage=5.0,
    )
    assert order.price == 50000.05
    assert "BTCUSDT" in engine.positions
    pos = engine.positions["BTCUSDT"]
    assert pos.quantity == 2.0
    assert pos.leverage == 5.0

    pnl = engine.update_position_pnl("BTCUSDT", 51000.00)
    assert pnl > 0


def test_xcrypto_broker_adapter():
    adapter = XCryptoBrokerAdapter()
    assert adapter.magic_number == MAGIC_NUMBER

    order_req = {
        "symbol": "ETHUSDT",
        "side": "BUY",
        "quantity": 10.0,
        "price": 3000.01,
        "order_type": "LIMIT",
        "leverage": 2.0,
    }
    res = adapter.place_order(order_req)
    assert res["status"] == "SUCCESS"
    assert res["magic_number"] == MAGIC_NUMBER

    positions = adapter.get_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "ETHUSDT"


def test_xcrypto_broker_adapter_execute_order():
    adapter = XCryptoBrokerAdapter()
    adapter.connect()

    order_req = SEBIOrderRequest(
        symbol="RELIANCE",
        exchange="NSE",
        order_type="BUY",
        product="MIS",
        quantity=5,
        price=2500.0,
    )

    with patch("institutional_integrations.xcrypto_engine.is_ist_market_open", return_value=True):
        resp = adapter.execute_order(order_req)
        assert resp.success is True
        assert resp.status == "FILLED"
        assert resp.ticket.startswith("XCRYPTO-")
        assert resp.price == 2500.0


def test_registry_integration():
    adapters = IndianBrokerPluginRegistry.list_registered_brokers()
    assert "XCRYPTO" in adapters
