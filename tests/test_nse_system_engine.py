"""
Tests for NSE System Multi-Factor & Market Regime Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.nse_system_engine import (
    NSESystemEngine,
    NSESystemBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_NSE_SYSTEM,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_market_regime_and_composite_scoring():
    engine = NSESystemEngine(top_n_sectors=3)
    assert engine.magic_number == MAGIC_NUMBER_NSE_SYSTEM

    # Bullish market regime test
    regime_bullish = engine.evaluate_market_regime(22500.0, 22100.0)
    assert regime_bullish["is_bullish"]

    # Bearish market regime test
    regime_bearish = engine.evaluate_market_regime(21800.0, 22100.0)
    assert not regime_bearish["is_bullish"]

    universe = [
        {"symbol": "RELIANCE", "sector": "ENERGY", "roce": 20.0, "profit_growth": 18.0, "pe_ratio": 0.9, "rsi": 62.0, "close": 2500.02},
        {"symbol": "TCS", "sector": "IT", "roce": 25.0, "profit_growth": 20.0, "pe_ratio": 0.8, "rsi": 58.0, "close": 3600.04},
        {"symbol": "WEAKSTOCK", "sector": "IT", "roce": 2.0, "profit_growth": -10.0, "pe_ratio": 3.0, "rsi": 30.0, "close": 50.0},
    ]

    # Bearish regime blocks top picks
    picks_bearish = engine.scan_top_picks(universe, regime_bullish=False)
    assert len(picks_bearish) == 0

    # Bullish regime filters top picks
    picks_bullish = engine.scan_top_picks(universe, regime_bullish=True, allowed_sectors=["ENERGY", "IT"])
    assert len(picks_bullish) == 2
    assert picks_bullish[0]["symbol"] in ("TCS", "RELIANCE")
    assert picks_bullish[0]["last_price"] == round_tick_005(picks_bullish[0]["last_price"])


def test_nse_system_broker_adapter():
    adapter = NSESystemBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("NSE_SYSTEM") == NSESystemBrokerAdapter

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

    with patch("institutional_integrations.nse_system_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 2500.00
        assert res.ticket.startswith("NSESYS-")
