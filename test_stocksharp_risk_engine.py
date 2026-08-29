"""
Unit and Integration Tests for StockSharp Risk Manager.
"""

from datetime import datetime, timedelta
import pytest

from institutional_integrations.stocksharp_risk_engine import (
    StockSharpRiskManager,
    RiskAction,
)


def test_stocksharp_order_volume_and_frequency_rules():
    rm = StockSharpRiskManager(max_order_volume=5.0, max_orders_per_minute=2)
    now = datetime(2026, 7, 16, 12, 0, 0)

    # 1. Volume rule breach (6.0 > 5.0)
    vols = rm.evaluate_order(volume=6.0, current_time=now)
    assert len(vols) == 1
    assert vols[0].rule_name == "RiskOrderVolumeRule"
    assert vols[0].action == RiskAction.CANCEL_ORDERS

    # 2. Valid orders 1 and 2
    rm.evaluate_order(volume=2.0, current_time=now)
    rm.evaluate_order(volume=2.0, current_time=now + timedelta(seconds=10))

    # 3. Frequency rule breach (3rd order in same minute)
    freq_vols = rm.evaluate_order(volume=2.0, current_time=now + timedelta(seconds=20))
    assert len(freq_vols) == 1
    assert freq_vols[0].rule_name == "RiskOrderFreqRule"
    assert freq_vols[0].action == RiskAction.STOP_TRADING


def test_stocksharp_pnl_and_slippage_rules():
    rm = StockSharpRiskManager(max_realized_loss_usd=1000.0, max_unrealized_loss_usd=500.0, max_slippage_pips=3.0)
    now = datetime(2026, 7, 16, 12, 0, 0)

    # Unrealized loss breach
    pnl_vols = rm.evaluate_pnl_rule(realized_pnl=0.0, unrealized_pnl=-600.0, current_time=now)
    assert len(pnl_vols) == 1
    assert pnl_vols[0].rule_name == "RiskPnLRule_Unrealized"
    assert pnl_vols[0].action == RiskAction.CLOSE_POSITIONS

    # Slippage breach
    slip_vols = rm.evaluate_slippage_rule(actual_slippage_pips=4.5, current_time=now)
    assert len(slip_vols) == 1
    assert slip_vols[0].rule_name == "RiskSlippageRule"


def test_stocksharp_error_rule():
    rm = StockSharpRiskManager(max_consecutive_errors=2)
    now = datetime(2026, 7, 16, 12, 0, 0)

    # 1st error -> No breach
    e1 = rm.record_order_error(now)
    assert len(e1) == 0

    # 2nd error -> Breach
    e2 = rm.record_order_error(now + timedelta(seconds=5))
    assert len(e2) == 1
    assert e2[0].rule_name == "RiskErrorRule"
    assert e2[0].action == RiskAction.STOP_TRADING
