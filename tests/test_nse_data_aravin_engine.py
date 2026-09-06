"""
Tests for NSE Data Aravin Client Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.nse_data_aravin_engine import (
    NSEDataAravinEngine,
    NSEDataAravinBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_NSE_DATA_ARAVIN,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_equity_quote_and_option_chain_parsing():
    engine = NSEDataAravinEngine()
    assert engine.magic_number == MAGIC_NUMBER_NSE_DATA_ARAVIN

    raw_quote = {
        "symbol": "RELIANCE",
        "priceInfo": {
            "lastPrice": "2500.02",
            "open": "2480.00",
            "intraDayHighLow": {"max": 2515.00, "min": 2470.00},
            "pChange": 1.80,
        },
    }

    quote_res = engine.parse_equity_quote(raw_quote)
    assert quote_res["symbol"] == "RELIANCE"
    assert quote_res["last_price"] == 2500.00
    assert quote_res["recommended_signal"] == "BUY"

    raw_option_chain = [
        {"strikePrice": 2480.0, "CE": {"openInterest": 50000, "lastPrice": 45.02}, "PE": {"openInterest": 120000, "lastPrice": 15.00}},
        {"strikePrice": 2500.0, "CE": {"openInterest": 150000, "lastPrice": 30.00}, "PE": {"openInterest": 180000, "lastPrice": 28.00}},
    ]

    oc_res = engine.parse_equity_option_chain(raw_option_chain, underlying_price=2500.0)
    assert oc_res["underlying_price"] == 2500.00
    assert oc_res["total_ce_oi"] == 200000
    assert oc_res["total_pe_oi"] == 300000
    assert oc_res["pcr"] == 1.5


def test_nse_data_aravin_broker_adapter():
    adapter = NSEDataAravinBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("NSE_DATA_ARAVIN") == NSEDataAravinBrokerAdapter

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

    with patch("institutional_integrations.nse_data_aravin_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 2500.00
        assert res.ticket.startswith("NSEDATA-")
