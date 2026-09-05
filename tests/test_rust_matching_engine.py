"""
Tests for Rust High-Performance Orderbook Matching Engine Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.rust_matching_engine import (
    OrderbookL2,
    RustMatchingEngineBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_RUST_MATCHING_ENGINE,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_orderbook_matching_and_depth():
    orderbook = OrderbookL2("RELIANCE")
    assert orderbook.magic_number == MAGIC_NUMBER_RUST_MATCHING_ENGINE

    # Place ask limit order: Sell 100 shares @ 2500.00
    res_ask = orderbook.place_limit_order("ASK", 2500.02, 100.0)
    assert res_ask["price"] == 2500.00
    assert not res_ask["is_filled"]

    depth = orderbook.get_orderbook_depth()
    assert depth["best_ask"] == 2500.00
    assert depth["ask_depth"][0]["volume"] == 100.0

    # Place bid limit order: Buy 50 shares @ 2500.00 (Crosses ask queue)
    res_bid = orderbook.place_limit_order("BID", 2500.00, 50.0)
    assert res_bid["is_filled"]
    assert res_bid["filled_size"] == 50.0
    assert len(res_bid["fills"]) == 1
    assert res_bid["fills"][0]["quantity"] == 50.0

    # Remaining ask depth should be 50 shares @ 2500.00
    updated_depth = orderbook.get_orderbook_depth()
    assert updated_depth["best_ask"] == 2500.00
    assert updated_depth["ask_depth"][0]["volume"] == 50.0


def test_rust_matching_broker_adapter():
    adapter = RustMatchingEngineBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("RUST_MATCHING_ENGINE") == RustMatchingEngineBrokerAdapter

    req = SEBIOrderRequest(
        symbol="RELIANCE",
        quantity=10,
        price=2500.02,
        order_type="BID",
        product="MIS",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.rust_matching_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.price == 2500.00
        assert res.ticket.startswith("RUSTENG-")
