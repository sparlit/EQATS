"""
Unit tests for NSEBSEApiEngine and NSEBSEApiBrokerAdapter (Repo 085 Adaptation, Magic 9100082)
"""

from unittest.mock import patch

import pytest
from institutional_integrations.nse_bse_api_bshada_engine import (
    NSEBSEApiEngine,
    NSEBSEApiBrokerAdapter,
    MAGIC_NUMBER,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_nse_bse_api_engine():
    engine = NSEBSEApiEngine()

    quote = engine.parse_quote_payload({
        "symbol": "RELIANCE",
        "nse_price": 2500.03,
        "bse_price": 2502.10,
        "p_change_nse": 1.2,
        "p_change_bse": 1.3,
    })
    assert quote.symbol == "RELIANCE"
    assert quote.nse_price == 2500.05
    assert quote.bse_price == 2502.10
    assert quote.spread == 2.05

    options = [
        {"strike_price": 2400.0, "ce_oi": 1000, "pe_oi": 1500},
        {"strike_price": 2500.0, "ce_oi": 2000, "pe_oi": 1800},
        {"strike_price": 2600.0, "ce_oi": 1500, "pe_oi": 800},
    ]
    opt_summary = engine.analyze_option_chain(options)
    assert opt_summary["pcr"] > 0
    assert opt_summary["max_pain_strike"] > 0

    stocks = [
        {"symbol": "INFY", "pChange": "2.5"},
        {"symbol": "TCS", "pChange": "-1.5"},
        {"symbol": "WIPRO", "pChange": "3.0"},
    ]
    movers = engine.classify_market_movers(stocks)
    assert len(movers["top_gainers"]) == 3
    assert movers["top_gainers"][0]["symbol"] == "WIPRO"


def test_nse_bse_api_broker_adapter():
    adapter = NSEBSEApiBrokerAdapter()
    assert adapter.magic_number == MAGIC_NUMBER
    adapter.connect()
    assert adapter.is_connected() is True

    req = SEBIOrderRequest(
        symbol="INFY",
        exchange="NSE",
        order_type="BUY",
        product="MIS",
        quantity=50,
        price=1500.03,
    )

    with patch("institutional_integrations.nse_bse_api_bshada_engine.is_ist_market_open", return_value=True):
        resp = adapter.execute_order(req)
        assert resp.success is True
        assert resp.status == "FILLED"
        assert resp.price == 1500.05
        assert resp.ticket.startswith("NSEBSE-INFY-")


def test_registry_integration():
    brokers = IndianBrokerPluginRegistry.list_registered_brokers()
    assert "NSE_BSE_API_BSHADA" in brokers
