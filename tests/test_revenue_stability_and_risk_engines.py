"""
Unit Tests for Revenue Stability, Drawdown Circuit Breakers, Slippage Guards, and Multi-Broker Failover Engines
"""

import pytest
from institutional_integrations.nse_var_dashboard_engine import NSEVaRDashboardEngine
from institutional_integrations.orderflowmap_engine import OrderFlowMapEngine
from institutional_integrations.rust_finance_engine import RustFinanceEngine
from institutional_integrations.algo_trade_aravin_engine import AlgoTradeAravinEngine


def test_drawdown_circuit_breaker():
    engine = NSEVaRDashboardEngine(max_drawdown_pct=2.0)

    # 1. Normal trading (1.0% drawdown) -> ALLOW_ORDER
    res_normal = engine.evaluate_drawdown_circuit_breaker(
        current_portfolio_value=990000.0,
        peak_portfolio_value=1000000.0
    )
    assert res_normal["circuit_breaker_triggered"] is False
    assert res_normal["action"] == "ALLOW_ORDER"

    # 2. Drawdown exceeds 2.0% (2.5% drawdown) -> HALT_NEW_ENTRIES
    res_halt = engine.evaluate_drawdown_circuit_breaker(
        current_portfolio_value=975000.0,
        peak_portfolio_value=1000000.0
    )
    assert res_halt["circuit_breaker_triggered"] is True
    assert res_halt["action"] == "HALT_NEW_ENTRIES"


def test_orderbook_slippage_guard():
    engine = OrderFlowMapEngine(max_allowed_spread=0.10, min_depth_qty=100)

    # 1. Tight spread (0.05 INR), sufficient depth (500) -> EXECUTE
    res_ok = engine.evaluate_orderbook_slippage_guard(
        best_bid=500.0, best_ask=500.05, bid_depth_qty=500, ask_depth_qty=500
    )
    assert res_ok["slippage_guard_passed"] is True
    assert res_ok["action"] == "EXECUTE"

    # 2. Wide spread (0.25 INR) -> REJECT
    res_wide = engine.evaluate_orderbook_slippage_guard(
        best_bid=500.0, best_ask=500.25, bid_depth_qty=500, ask_depth_qty=500
    )
    assert res_wide["slippage_guard_passed"] is False
    assert res_wide["reason"] == "SPREAD_TOO_WIDE"


def test_delta_neutral_strangle_theta_decay():
    engine = RustFinanceEngine(risk_free_rate=0.07)

    strangle = engine.frame_delta_neutral_strangle(
        spot=22000.0, volatility=0.15, time_to_expiry=7/365, target_delta=0.15
    )

    assert strangle["call_strike"] > 22000.0
    assert strangle["put_strike"] < 22000.0
    assert strangle["daily_theta_income"] > 0.0
    assert strangle["strategy"] == "DELTA_NEUTRAL_STRANGLE"


def test_multi_broker_auto_failover():
    engine = AlgoTradeAravinEngine()

    # Refresh only UPSTOX session (FINVASIA is inactive)
    engine.refresh_broker_session("UPSTOX", "token_upstox_abc")

    res = engine.route_order_execution_with_failover(
        primary_broker="FINVASIA",
        request_data={"symbol": "NIFTY", "price": 22000.0, "quantity": 50}
    )

    assert res["success"] is True
    assert res["broker"] == "UPSTOX"
    assert res["failover_triggered"] is True
