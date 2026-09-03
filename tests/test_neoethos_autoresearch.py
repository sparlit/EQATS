"""
Unit and Integration Tests for Neoethos AutoResearch Engine.
"""

from typing import Any

import pytest

from institutional_integrations.neoethos_autoresearch import NeoethosAutoResearchEngine, ResearchObjectiveConfig


def test_neoethos_evaluate_hypothesis() -> None:
    engine = NeoethosAutoResearchEngine(ResearchObjectiveConfig(min_t_stat_threshold=1.5))
    returns = [0.0015, -0.0002, 0.0018, 0.0012, 0.0009, 0.0011, 0.0014]
    res = engine.evaluate_hypothesis(returns, hypothesis_id="HYP_TEST")
    assert res.hypothesis_id == "HYP_TEST"
    assert res.t_stat > 1.5
    assert res.passed is True
    assert res.combined_score > 0.0


def test_neoethos_feature_shuffle_experiment() -> None:
    engine = NeoethosAutoResearchEngine()
    returns = [0.002, 0.0025, 0.0018, 0.0022, 0.0019, 0.0021, 0.0023]
    res = engine.run_feature_shuffle_experiment(returns, num_shuffles=50, seed=123)
    assert "original_combined_score" in res
    assert "p_value" in res
    assert isinstance(res["p_value"], float)


def test_neoethos_soft_voting_ensemble_replay() -> None:
    engine = NeoethosAutoResearchEngine()
    signals = {"strat1": [0.001, -0.0005, 0.002, 0.0015], "strat2": [0.0008, -0.0002, 0.0015, 0.0012]}
    stats = engine.run_soft_voting_ensemble_replay(signals)
    assert stats.total_trades == 4
    assert stats.win_rate == 75.0
    assert stats.profit_factor > 1.0
