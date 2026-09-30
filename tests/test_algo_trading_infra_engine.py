# codespell:ignore IST
"""
Unit test suite for Algo Trading Infrastructure Integration Engine.
Tests lifecycle execution, IST market session, orderbook depth buffer, and plugin registry.
"""

import datetime

from src.institutional_integrations.algo_trading_infra_engine import (
    MAGIC_NUMBER_ALGO_TRADING_INFRA,
    AlgoTradingInfraEngine,
    OrderBookDepthBuffer,
    is_ist_market_session_active,
    round_to_ist_tick,
)
from src.institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_ist_market_session_and_tick_rounding() -> None:
    """
    Verifies price tick rounding to 0.05 INR and IST market session validation logic.
    """
    assert round_to_ist_tick(100.02) == 100.00
    assert round_to_ist_tick(100.03) == 100.05
    assert round_to_ist_tick(100.07) == 100.05
    assert round_to_ist_tick(100.08) == 100.10

    tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    ist_time = datetime.datetime(2025, 3, 12, 10, 0, 0, tzinfo=tz)
    assert is_ist_market_session_active(ist_time) is True

    weekend_time = datetime.datetime(2025, 3, 15, 10, 0, 0, tzinfo=tz)
    assert is_ist_market_session_active(weekend_time) is False


def test_orderbook_depth_buffer_slippage() -> None:
    """
    Tests orderbook depth buffer level updates and slippage impact estimation calculations.
    """
    buffer = OrderBookDepthBuffer(depth_levels=3)
    asks = [
        {"price": 100.0, "quantity": 10.0},
        {"price": 101.0, "quantity": 10.0},
        {"price": 102.0, "quantity": 10.0},
    ]
    bids = [
        {"price": 99.0, "quantity": 10.0},
        {"price": 98.0, "quantity": 10.0},
    ]
    buffer.update_depth(bids=bids, asks=asks)

    slip_small = buffer.estimate_slippage(5.0, "BUY")
    assert slip_small["expected_price"] == 100.0
    assert slip_small["slippage_pct"] == 0.0

    slip_large = buffer.estimate_slippage(15.0, "BUY")
    assert slip_large["expected_price"] == 100.35
    assert slip_large["slippage_pct"] > 0.3


def test_algo_trading_infra_engine_lifecycle() -> None:
    """
    Tests AlgoTradingInfraEngine order execution lifecycle from placement to modification/closure.
    """
    engine = AlgoTradingInfraEngine(
        is_sandbox=True,
        max_allowed_slippage_pct=0.5,
    )
    assert engine.magic_number == MAGIC_NUMBER_ALGO_TRADING_INFRA
    assert engine.is_connected() is True

    account = engine.get_account_info()
    assert account["balance"] == 2500000.0
    assert account["magic_number"] == MAGIC_NUMBER_ALGO_TRADING_INFRA

    bids = [{"price": 999.0, "quantity": 100.0}]
    asks = [{"price": 1000.0, "quantity": 100.0}]
    engine.update_market_depth("RELIANCE", bids, asks)

    req = SEBIOrderRequest(
        symbol="RELIANCE",
        order_type="BUY",
        quantity=10,
        price=1000.0,
        product="CNC",
        exchange="NSE",
    )
    res = engine.execute_order(req)
    assert res.success is True
    assert res.status == "FILLED"
    assert res.price == 1000.0

    open_orders = engine.get_open_orders()
    assert len(open_orders) == 1

    mod_res = engine.modify_order(res.ticket, price=1005.0)
    assert mod_res is True

    close_res = engine.close_order(res.ticket, "RELIANCE")
    assert close_res.success is True
    assert len(engine.get_open_orders()) == 0


def test_microkernel_registry_integration() -> None:
    """
    Verifies dynamic registration of ALGO_TRADING_INFRA in IndianBrokerPluginRegistry.
    """
    cls = IndianBrokerPluginRegistry.get_adapter_class("ALGO_TRADING_INFRA")
    assert cls is AlgoTradingInfraEngine
