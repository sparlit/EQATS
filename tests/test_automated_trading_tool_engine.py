"""
Unit tests for Automated Trading Tool Suite Engine (`src/institutional_integrations/automated_trading_tool_engine.py`).
"""

import datetime
import zoneinfo

import pytest

from institutional_integrations.automated_trading_tool_engine import (
    MAGIC_NUMBER_DISPATCHER,
    MAGIC_NUMBER_ROUTER,
    AutomatedExecutionRiskRouter,
    AutomatedTradingToolAdapter,
    MultiStrategyAgenticSignalDispatcher,
    is_ist_market_session_active,
    round_to_ist_tick,
)
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry, SEBIOrderRequest


def test_round_to_ist_tick():
    assert round_to_ist_tick(100.03) == 100.05
    assert round_to_ist_tick(100.02) == 100.00
    assert round_to_ist_tick(100.07) == 100.05
    assert round_to_ist_tick(-10) == 0.0


def test_is_ist_market_session_active():
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    # Tuesday 10:30 AM IST -> Active
    active_dt = datetime.datetime(2025, 3, 11, 10, 30, tzinfo=ist)
    assert is_ist_market_session_active(active_dt) is True

    # Tuesday 08:30 AM IST -> Inactive
    early_dt = datetime.datetime(2025, 3, 11, 8, 30, tzinfo=ist)
    assert is_ist_market_session_active(early_dt) is False

    # Saturday 11:00 AM IST -> Inactive
    weekend_dt = datetime.datetime(2025, 3, 15, 11, 0, tzinfo=ist)
    assert is_ist_market_session_active(weekend_dt) is False


def test_automated_execution_risk_router():
    router = AutomatedExecutionRiskRouter(max_slice_lot=10.0, max_position_limit=100000.0)
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    active_dt = datetime.datetime(2025, 3, 11, 11, 0, tzinfo=ist)

    # Test Order Slicing & Approval
    res = router.slice_and_validate_order(
        symbol="RELIANCE",
        action="BUY",
        quantity=25.0,
        price=2500.12,
        current_portfolio_value=0.0,
        dt=active_dt,
    )

    assert res["approved"] is True
    assert res["slice_count"] == 3
    assert res["slices"][0]["quantity"] == 10.0
    assert res["slices"][1]["quantity"] == 10.0
    assert res["slices"][2]["quantity"] == 5.0
    assert res["magic_number"] == MAGIC_NUMBER_ROUTER

    # Test Risk Limit Exceeded
    res_limit = router.slice_and_validate_order(
        symbol="RELIANCE",
        action="BUY",
        quantity=100.0,
        price=2500.0,
        current_portfolio_value=900000.0,
        dt=active_dt,
    )
    assert res_limit["approved"] is False
    assert "Position limit exceeded" in res_limit["reason"]


def test_multistratey_agentic_signal_dispatcher():
    dispatcher = MultiStrategyAgenticSignalDispatcher(rsi_period=14, fast_ma=5, slow_ma=10)
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    active_dt = datetime.datetime(2025, 3, 11, 11, 0, tzinfo=ist)

    # Generate synthetic price history with downward trend then oversold dip
    prices = [100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 83.0, 85.0]
    res = dispatcher.generate_signal("INFY", prices, 85.0, dt=active_dt)

    assert res["symbol"] == "INFY"
    assert res["magic_number"] == MAGIC_NUMBER_DISPATCHER
    assert "price" in res
    assert "action" in res


def test_automated_trading_tool_adapter():
    adapter = AutomatedTradingToolAdapter(is_sandbox=True)
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    # Verify Microkernel Registration
    reg_cls = IndianBrokerPluginRegistry.get_adapter_class("AUTOMATED_TRADING_TOOL")
    assert reg_cls is AutomatedTradingToolAdapter

    # Execute Order
    req = SEBIOrderRequest(
        symbol="TCS",
        order_type="BUY",
        quantity=10.0,
        price=3500.0,
        product="CNC",
        exchange="NSE",
    )
    resp = adapter.execute_order(req)
    assert resp.success is True
    assert resp.ticket.startswith("ATT_")

    open_orders = adapter.get_open_orders()
    assert len(open_orders) == 1

    # Modify & Close Order
    assert adapter.modify_order(resp.ticket, price=3505.0) is True
    close_resp = adapter.close_order(resp.ticket, "TCS")
    assert close_resp.success is True
    assert len(adapter.get_open_orders()) == 0

    assert adapter.disconnect() is True
