"""
Tests for Rust Finance Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.rust_finance_engine import (
    RustFinanceEngine,
    RustFinanceBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_RUST_FINANCE,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_black_scholes_and_var_calculations():
    engine = RustFinanceEngine()
    assert engine.magic_number == MAGIC_NUMBER_RUST_FINANCE

    bs_call = engine.calculate_black_scholes(spot=25000.0, strike=25000.0, time_to_expiry=0.1, volatility=0.20, option_type="CALL")
    assert bs_call["price"] > 0.0
    assert 0.45 < bs_call["delta"] < 0.60

    bs_put = engine.calculate_black_scholes(spot=25000.0, strike=25000.0, time_to_expiry=0.1, volatility=0.20, option_type="PUT")
    assert bs_put["price"] > 0.0
    assert -0.55 < bs_put["delta"] < -0.40

    var_val = engine.calculate_value_at_risk(portfolio_value=1000000.0, daily_volatility=0.015, confidence_level=0.99, time_horizon_days=1)
    assert var_val > 0.0


def test_rust_finance_broker_adapter():
    adapter = RustFinanceBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("RUST_FINANCE") == RustFinanceBrokerAdapter

    req = SEBIOrderRequest(
        symbol="NIFTY24SEPFUT",
        quantity=50,
        price=25150.02,
        order_type="BUY",
        product="NRML",
        exchange="NFO",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.rust_finance_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 25150.00
        assert res.ticket.startswith("RF-")
