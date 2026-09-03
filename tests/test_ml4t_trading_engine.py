"""
Unit and Integration Tests for ML4T Financial ML Engine.
"""

from datetime import datetime, timedelta
from typing import Any

import pytest

from institutional_integrations.ml4t_trading_engine import EigenportfolioDecomposition, PurgedWalkForwardCV


def test_purged_walk_forward_cv() -> None:
    cv = PurgedWalkForwardCV(train_days=100, val_days=30, embargo_days=5, num_folds=2)
    start_dt = datetime(2026, 1, 1, 0, 0, 0)
    splits = cv.generate_splits(start_dt)
    assert len(splits) == 2
    f1 = splits[0]
    assert f1.fold_index == 1
    assert f1.train_end == start_dt + timedelta(days=100)
    assert f1.embargo_end == f1.train_end + timedelta(days=5)
    assert f1.val_start == f1.embargo_end
    assert f1.val_end == f1.val_start + timedelta(days=30)


def test_eigenportfolio_decomposition() -> None:
    pca_engine = EigenportfolioDecomposition()
    returns_data = {
        "AAPL": [0.01, -0.02, 0.015, 0.005, -0.01, 0.02],
        "MSFT": [0.008, -0.018, 0.012, 0.004, -0.008, 0.018],
        "GOOGL": [0.012, -0.022, 0.018, 0.006, -0.012, 0.022],
    }
    res = pca_engine.compute_eigenportfolios(returns_data, n_components=2)
    assert res.num_components == 2
    assert len(res.explained_variance_ratios) == 2
    assert "AAPL" in res.first_eigenportfolio_weights
    assert "MSFT" in res.first_eigenportfolio_weights
    assert "GOOGL" in res.first_eigenportfolio_weights
