"""
Tests for Virtual Stock Exchange (VSE) Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.vse_engine import (
    VirtualDematAccount,
    VSEBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_VSE,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_virtual_demat_account():
    demat = VirtualDematAccount(username="test_trader", initial_cash=100000.0)
    assert demat.magic_number == MAGIC_NUMBER_VSE

    # Buy shares
    res_buy = demat.buy_share("RELIANCE", 10, 2500.03)
    assert res_buy["success"]
    assert res_buy["price"] == 2500.05
    assert demat.cash_balance == 100000.0 - 25000.50

    # Summary check
    summary = demat.get_portfolio_summary({"RELIANCE": 2600.00})
    assert summary["cash_balance"] == 74999.50
    assert summary["market_value"] == 26000.00
    assert summary["unrealized_pnl"] == pytest.approx(999.50)

    # Sell shares
    res_sell = demat.sell_share("RELIANCE", 5, 2600.00)
    assert res_sell["success"]
    assert res_sell["pnl"] == pytest.approx(499.75)
    assert demat.holdings["RELIANCE"]["quantity"] == 5


def test_vse_broker_adapter():
    adapter = VSEBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("VSE_DEMAT") == VSEBrokerAdapter

    req = SEBIOrderRequest(
        symbol="INFY",
        quantity=10,
        price=1500.02,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.vse_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 1500.00
        assert res.ticket.startswith("VSE-")
