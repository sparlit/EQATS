"""
Tests for NSE Option Interest (OI) Visualizer Engine Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.nse_oi_visualizer_engine import (
    NSEOIVisualizerEngine,
    NSEOIVisualizerBrokerAdapter,
    black76_option_price,
    round_tick_005,
    MAGIC_NUMBER_NSE_OI_VISUALIZER,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_black76_option_pricing():
    # Call option pricing
    call_price = black76_option_price(
        is_call=True,
        futures_price=22000.0,
        strike_price=22000.0,
        time_to_exp_years=0.05,
        risk_free_rate=0.07,
        volatility=0.15,
    )
    assert call_price > 0.0
    assert call_price == round_tick_005(call_price)

    # Put option pricing
    put_price = black76_option_price(
        is_call=False,
        futures_price=22000.0,
        strike_price=22000.0,
        time_to_exp_years=0.05,
        risk_free_rate=0.07,
        volatility=0.15,
    )
    assert put_price > 0.0
    assert put_price == round_tick_005(put_price)


def test_option_chain_oi_analytics():
    engine = NSEOIVisualizerEngine()
    assert engine.magic_number == MAGIC_NUMBER_NSE_OI_VISUALIZER

    chain_sample = [
        {"strike_price": 21800.0, "ce_oi": 50000, "pe_oi": 150000, "ce_change_oi": 2000, "pe_change_oi": 20000},
        {"strike_price": 22000.0, "ce_oi": 120000, "pe_oi": 200000, "ce_change_oi": 5000, "pe_change_oi": 35000},
        {"strike_price": 22200.0, "ce_oi": 180000, "pe_oi": 80000, "ce_change_oi": 25000, "pe_change_oi": 10000},
    ]

    analysis = engine.analyze_option_chain_oi(
        underlying_price=22000.0,
        option_chain=chain_sample,
        risk_free_rate=0.07,
        volatility=0.15,
        time_to_exp_years=0.05,
    )

    assert analysis["underlying_price"] == 22000.0
    assert analysis["total_ce_oi"] == 350000
    assert analysis["total_pe_oi"] == 430000
    assert analysis["pcr_oi"] > 1.0
    assert analysis["atm_strike"] == 22000.0
    assert analysis["atm_ce_black76_price"] > 0.0
    assert analysis["recommended_signal"] == "BUY"


def test_nse_oi_visualizer_broker_adapter():
    adapter = NSEOIVisualizerBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("NSE_OI_VISUALIZER") == NSEOIVisualizerBrokerAdapter

    req = SEBIOrderRequest(
        symbol="NIFTY",
        quantity=50,
        price=22000.02,
        order_type="BUY",
        product="MIS",
        exchange="NFO",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.nse_oi_visualizer_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 22000.00
        assert res.ticket.startswith("NSEOIVIZ-")
