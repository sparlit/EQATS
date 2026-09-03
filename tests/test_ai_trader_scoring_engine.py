"""
Unit and Integration Tests for AI-Trader Scoring Engine.
"""

from typing import Any

import pytest

from institutional_integrations.ai_trader_scoring_engine import (
    AITraderChallengeScoringEngine,
    AITraderSignalQualityEvaluator,
)


def test_ai_trader_signal_quality_evaluator() -> None:
    evaluator = AITraderSignalQualityEvaluator()
    signals = [{"direction": "BUY"}, {"direction": "BUY"}, {"direction": "SELL"}, {"direction": "BUY"}]
    returns = [0.02, 0.01, -0.015, -0.005]
    metrics = evaluator.evaluate_signal_quality(signals, returns)
    assert metrics.directional_accuracy_pct == 75.0
    assert metrics.composite_quality_score > 0.0
    assert metrics.grade in ["A+", "A", "B", "C"]


def test_ai_trader_challenge_scoring_and_leaderboard() -> None:
    scoring_engine = AITraderChallengeScoringEngine(
        allowed_drawdown_pct=5.0, drawdown_penalty=1.0, max_position_pct=50.0, max_drawdown_pct=15.0,
    )
    trades_agent1 = [
        {"symbol": "BTC", "side": "BUY", "price": 50000.0, "quantity": 0.5},
        {"symbol": "BTC", "side": "SELL", "price": 55000.0, "quantity": 0.5},
    ]
    trades_agent2 = [
        {"symbol": "ETH", "side": "BUY", "price": 3000.0, "quantity": 5.0},
        {"symbol": "ETH", "side": "SELL", "price": 3100.0, "quantity": 5.0},
    ]
    res1 = scoring_engine.score_agent_trades("AGENT_BULL", 100000.0, trades_agent1)
    res2 = scoring_engine.score_agent_trades("AGENT_BEAR", 100000.0, trades_agent2)
    assert res1.return_pct == 2.5
    assert res1.disqualified_reason is None
    leaderboard = scoring_engine.rank_leaderboard([res1, res2])
    assert len(leaderboard) == 2
    assert leaderboard[0].rank == 1
    assert leaderboard[0].agent_id == "AGENT_BULL"
