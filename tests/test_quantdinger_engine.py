"""
Unit and Integration Tests for QuantDinger Engine.
"""

from typing import Any

import pytest

from institutional_integrations.quantdinger_engine import (
    GridMode,
    QuantDingerFactorResearchEngine,
    QuantDingerGridEngine,
)


def test_quantdinger_arithmetic_grid() -> None:
    grid = QuantDingerGridEngine(lower_bound=100.0, upper_bound=200.0, grid_count=10, grid_mode=GridMode.ARITHMETIC)
    assert len(grid.state.grid_levels) == 11
    assert grid.state.grid_levels[0].price == 100.0
    assert grid.state.grid_levels[-1].price == 200.0
    hits, pnl = grid.evaluate_grid_hits(110.0)
    assert len(hits) >= 1
    assert any(l.price == 110.0 and l.executed for l in grid.state.grid_levels)


def test_quantdinger_geometric_grid() -> None:
    grid = QuantDingerGridEngine(lower_bound=100.0, upper_bound=400.0, grid_count=2, grid_mode=GridMode.GEOMETRIC)
    assert len(grid.state.grid_levels) == 3
    assert grid.state.grid_levels[1].price == 200.0


def test_quantdinger_factor_research_engine() -> None:
    factor_engine = QuantDingerFactorResearchEngine()
    factor_vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    returns = [0.01, 0.02, 0.03, 0.04, 0.05]
    score = factor_engine.evaluate_factor_ic(factor_vals, returns, factor_name="TrendFactor")
    assert score.factor_name == "TrendFactor"
    assert score.ic_score == 1.0
    assert score.direction == "BULLISH"
