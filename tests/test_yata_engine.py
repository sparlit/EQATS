"""
Tests for YATA High-Performance Technical Analysis Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.yata_engine import (
    YATATechnicalEngine,
    YATABrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_YATA,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_yata_indicators_and_signals():
    engine = YATATechnicalEngine(period_hma=9)
    assert engine.magic_number == MAGIC_NUMBER_YATA

    # Generate synthetic price series (30 candles)
    base_price = 100.0
    prices = [base_price + i * 0.5 for i in range(30)]

    hma_val = engine.compute_hma(prices, period=9)
    assert hma_val > 0.0

    eval_result = engine.evaluate_composite_indicators(prices, high=115.0, low=114.0, close=114.5)
    assert eval_result["signal"] in ("BUY", "SELL", "HOLD")
    assert eval_result["magic_number"] == MAGIC_NUMBER_YATA


def test_yata_broker_adapter():
    adapter = YATABrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("YATA_TECHNICAL") == YATABrokerAdapter

    req = SEBIOrderRequest(
        symbol="TCS",
        quantity=10,
        price=3500.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.yata_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 3500.00
        assert res.ticket.startswith("YATA-")
