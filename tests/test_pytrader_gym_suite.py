"""
Unit tests for PyTrader & TradingGym Suite integration.
Verifies TradingGymRLAdapter and PyTraderDepthAnalyzer.
"""

from typing import Any

import pytest

from institutional_integrations.pytrader_gym_suite import PyTraderDepthAnalyzer, TradingGymRLAdapter


def test_trading_gym_rl_adapter() -> None:
    adapter = TradingGymRLAdapter(initial_balance=10000.0, fee_pct=0.001)
    init_state = adapter.reset()
    assert len(init_state) == 4
    assert init_state[0] == 1.0
    res_buy = adapter.step(action=1, current_price=100.0, returns_history=[0.01, 0.02, -0.005])
    assert adapter.position > 0.0
    assert adapter.balance == 0.0
    assert res_buy.reward is not None
    res_hold = adapter.step(action=0, current_price=105.0, returns_history=[0.01, 0.02, 0.05])
    assert res_hold.reward > 0.0
    assert res_hold.info["equity"] > 10000.0
    res_sell = adapter.step(action=2, current_price=105.0, returns_history=[0.01, 0.02, 0.0])
    assert adapter.position == 0.0
    assert adapter.balance > 10000.0


def test_pytrader_depth_analyzer() -> None:
    analyzer = PyTraderDepthAnalyzer()
    bids = [(100.0, 10.0), (99.5, 20.0), (99.0, 30.0)]
    asks = [(100.5, 5.0), (101.0, 10.0), (101.5, 5.0)]
    res = analyzer.analyze_depth(bids, asks, depth_levels=3)
    assert res.bid_depth_volume == 60.0
    assert res.ask_depth_volume == 20.0
    assert res.depth_ratio == 3.0
    assert res.imbalance_pct == 50.0
    assert res.buy_pressure == "HIGH_BUY"
