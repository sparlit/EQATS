"""
Unit and Integration Tests for Zipline Finance Engine.
"""
from typing import Any
import pytest
from institutional_integrations.zipline_finance_engine import ZiplineSlippageModel, ZiplineCommissionModel, ZiplineRiskControlEngine, OrderSide

def test_zipline_slippage_models() -> None:
    slippage_model = ZiplineSlippageModel(volume_limit_pct=0.05, price_impact_factor=0.1)
    res_vol = slippage_model.calculate_volume_share_slippage(order_quantity=100.0, bar_volume=1000.0, bar_price=100.0, side=OrderSide.BUY)
    assert res_vol.fill_price > 100.0
    assert res_vol.volume_share == 0.05
    model_fixed = ZiplineSlippageModel(fixed_spread_pips=2.0, pip_size=0.0001)
    res_fixed = model_fixed.calculate_fixed_slippage(bar_price=1.08, side=OrderSide.BUY, order_quantity=1.0)
    assert res_fixed.fill_price == 1.0802

def test_zipline_commission_models() -> None:
    comm = ZiplineCommissionModel()
    res_unit = comm.per_unit(quantity=1000.0, cost_per_unit=0.001)
    assert res_unit.commission_usd == 1.0
    res_dollar = comm.per_dollar(transaction_value_usd=10000.0, cost_per_dollar=0.0015)
    assert res_dollar.commission_usd == 15.0
    res_trade = comm.per_trade(quantity=100.0, transaction_value_usd=1000.0, cost_per_unit=0.001, minimum_fee_per_trade=1.0)
    assert res_trade.commission_usd == 1.0

def test_zipline_risk_controls() -> None:
    risk_controls = ZiplineRiskControlEngine(max_leverage=5.0, max_position_size_usd=20000.0, min_order_value_usd=10.0, max_order_value_usd=15000.0)
    check_pass = risk_controls.check_pre_trade_controls(order_value_usd=10000.0, current_portfolio_exposure_usd=10000.0, account_equity=100000.0)
    assert check_pass.passed is True
    check_fail = risk_controls.check_pre_trade_controls(order_value_usd=18000.0, current_portfolio_exposure_usd=10000.0, account_equity=100000.0)
    assert check_fail.passed is False
    assert len(check_fail.violations) > 0
