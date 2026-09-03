"""
Unit and Integration Tests for Backtrader Engine.
"""

from typing import Any

import pytest

from institutional_integrations.backtrader_engine import BacktraderAnalyzerEngine, BacktraderSizerEngine


def test_backtrader_analyzer_metrics() -> None:
    analyzer = BacktraderAnalyzerEngine()
    trade_pnls = [100.0, -50.0, 200.0, -30.0, 150.0]
    returns = [0.001, -0.0005, 0.002, -0.0003, 0.0015]
    metrics = analyzer.evaluate_performance(returns, trade_pnls, initial_balance=100000.0, years=1.0)
    assert metrics.total_trades == 5
    assert metrics.sqn_score > 0.0
    assert metrics.win_rate == 60.0
    assert metrics.annual_return_pct > 0.0


def test_backtrader_sizers() -> None:
    sizer = BacktraderSizerEngine()
    pct_res = sizer.percent_sizer(account_equity=100000.0, percent=2.0, leverage=100.0)
    assert pct_res.lot_size == 2.0
    assert pct_res.risk_amount_usd == 2000.0
    risk_res = sizer.risk_sizer(account_equity=100000.0, risk_pct=1.0, stop_loss_pips=20.0, pip_value_per_lot=10.0)
    assert risk_res.lot_size == 5.0
    assert risk_res.risk_amount_usd == 1000.0
