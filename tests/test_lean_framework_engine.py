"""
Unit and Integration Tests for Lean Framework Engine.
"""

from typing import Any

import pytest

from institutional_integrations.lean_framework_engine import (
    LeanMaximumDrawdownPercentPortfolio,
    PearsonCorrelationPairsTradingAlphaModel,
)


def test_lean_pearson_pairs_alpha_model() -> None:
    alpha_model = PearsonCorrelationPairsTradingAlphaModel(minimum_correlation=0.7, z_score_threshold=1.5)
    price_series = {
        "BTCUSDT": [50000.0, 50500.0, 51000.0, 51500.0, 52000.0, 55000.0],
        "ETHUSDT": [3000.0, 3030.0, 3060.0, 3090.0, 3120.0, 3150.0],
    }
    res = alpha_model.find_best_pair(price_series)
    assert res is not None
    assert res.asset1 == "BTCUSDT"
    assert res.asset2 == "ETHUSDT"
    assert res.correlation > 0.7
    assert res.signal == "SHORT_PAIR"


def test_lean_maximum_drawdown_portfolio_risk_manager() -> None:
    risk_mgr = LeanMaximumDrawdownPercentPortfolio(maximum_drawdown_percent=0.05, is_trailing=True)
    targets_safe = risk_mgr.manage_risk(100000.0, ["BTCUSDT", "ETHUSDT"])
    assert len(targets_safe) == 0
    risk_mgr.manage_risk(110000.0, ["BTCUSDT", "ETHUSDT"])
    assert risk_mgr.portfolio_high == 110000.0
    targets_liq = risk_mgr.manage_risk(100000.0, ["BTCUSDT", "ETHUSDT"])
    assert len(targets_liq) == 2
    assert targets_liq[0].target_quantity == 0.0
    assert "Liquidating" in targets_liq[0].reason
