"""
Tests for NSE VaR Dashboard Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.nse_var_dashboard_engine import (
    NSEVaRDashboardEngine,
    NSEVaRDashboardBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_NSE_VAR_DASHBOARD,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_historical_and_parametric_var():
    engine = NSEVaRDashboardEngine(confidence_level=0.99)
    assert engine.magic_number == MAGIC_NUMBER_NSE_VAR_DASHBOARD

    returns = [-0.03, -0.02, -0.015, -0.01, 0.005, 0.01, 0.012, 0.02, 0.025, 0.03]
    var_res = engine.compute_historical_var(returns, portfolio_value=1000000.0)
    assert var_res["var_amount"] > 0.0
    assert var_res["cvar_amount"] >= var_res["var_amount"]

    p_var = engine.compute_parametric_var(portfolio_value=1000000.0, mean_return=0.001, std_dev=0.015)
    assert p_var > 0.0


def test_nse_var_dashboard_broker_adapter():
    adapter = NSEVaRDashboardBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("NSE_VAR_DASHBOARD") == NSEVaRDashboardBrokerAdapter

    req = SEBIOrderRequest(
        symbol="RELIANCE",
        quantity=20,
        price=2950.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.nse_var_dashboard_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 2950.00
        assert res.ticket.startswith("VAR-")
