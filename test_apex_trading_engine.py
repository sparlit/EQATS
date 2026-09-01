"""
Unit and Integration Tests for Apex Trading Engine.
"""
from typing import Any
import pytest
from institutional_integrations.apex_trading_engine import ApexTradingRiskEngine, ApexTradingAISignalEngine

def test_apex_risk_var_and_cvar() -> None:
    risk_engine = ApexTradingRiskEngine()
    returns = [0.01, -0.02, 0.015, -0.018, 0.005, -0.025, 0.012]
    var_res = risk_engine.calculate_var_and_expected_shortfall(returns, portfolio_value=100000.0)
    assert var_res.var_95 > 0.0
    assert var_res.var_99 >= var_res.var_95
    assert var_res.expected_shortfall > 0.0

def test_apex_portfolio_concentration_and_greeks() -> None:
    risk_engine = ApexTradingRiskEngine()
    positions = [10000.0, 20000.0, 50000.0]
    conc = risk_engine.calculate_portfolio_concentration(positions)
    assert conc == 62.5
    options = [{'quantity': 2.0, 'option_type': 'CALL'}, {'quantity': 1.0, 'option_type': 'PUT'}]
    greeks = risk_engine.calculate_portfolio_greeks(options)
    assert abs(greeks.delta - 0.5) < 1e-06
    assert abs(greeks.gamma - 0.15) < 1e-06

def test_apex_pre_trade_risk_limits() -> None:
    risk_engine = ApexTradingRiskEngine(max_position_size=20000.0, max_portfolio_risk_pct=30.0, max_concentration_pct=70.0)
    check_pass = risk_engine.check_pre_trade_risk_limits(proposed_order_usd=15000.0, current_positions_usd=[10000.0], portfolio_value=100000.0)
    assert check_pass.approved is True
    check_fail = risk_engine.check_pre_trade_risk_limits(proposed_order_usd=25000.0, current_positions_usd=[10000.0], portfolio_value=100000.0)
    assert check_fail.approved is False
    assert len(check_fail.violations) > 0

def test_apex_ai_signal_engine() -> None:
    ai_engine = ApexTradingAISignalEngine()
    preds = ai_engine.predict_lstm_price_horizon(current_price=100.0, horizon_steps=5)
    assert len(preds) == 5
    assert preds[0].predicted_price > 0.0
    assert preds[0].confidence > 0.5
    patterns = ai_engine.detect_chart_patterns([10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0])
    assert len(patterns) > 0
    assert patterns[0]['pattern_name'] == 'Bull Flag'
