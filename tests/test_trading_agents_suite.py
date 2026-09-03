"""
Unit and Integration Tests for TradingAgents Multi-Agent Suite.
"""

from typing import Any

import pytest

from institutional_integrations.trading_agents_suite import (
    BearResearcherAgent,
    BullResearcherAgent,
    RiskDebaterAgent,
    TradingAgentsOrchestrator,
)


def test_bull_and_bear_agents() -> None:
    bull = BullResearcherAgent()
    bear = BearResearcherAgent()
    bull_score, bull_thesis = bull.evaluate("AAPL", technical_score=0.8, fundamental_score=0.9, sentiment_score=0.7)
    assert bull_score > 0.7
    assert "Bull Thesis" in bull_thesis
    bear_score, bear_thesis = bear.evaluate("AAPL", volatility=0.1, drawdown_pct=0.05, overbought_score=0.2)
    assert bear_score < 0.2
    assert "Bear Thesis" in bear_thesis


def test_trading_agents_orchestrator_debate() -> None:
    orchestrator = TradingAgentsOrchestrator()
    decision = orchestrator.run_debate_and_synthesize(
        symbol="BTCUSDT",
        technical_score=0.85,
        fundamental_score=0.9,
        sentiment_score=0.8,
        volatility=0.15,
        drawdown_pct=0.1,
        overbought_score=0.2,
        rounds=3,
    )
    assert decision.action == "BUY"
    assert decision.confidence > 0.8
    assert len(decision.debate_history) == 3
    assert "Debate completed" in decision.reasoning
