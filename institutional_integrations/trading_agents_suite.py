"""
TradingAgents Multi-Agent Debate & Orchestration Engine (EQATS Institutional Adaptation)
Adapted from TauricResearch/TradingAgents

Provides:
- BullResearcherAgent & BearResearcherAgent (Structured Adversarial Bull/Bear Debate)
- RiskDebaterAgent (Conservative, Neutral, Aggressive Risk Triad)
- TradingAgentsOrchestrator (Multi-Agent Swarm Orchestrator and Decision Synthesizer)
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

class AgentRole(str, Enum):
    BULL_RESEARCHER = 'BULL_RESEARCHER'
    BEAR_RESEARCHER = 'BEAR_RESEARCHER'
    CONSERVATIVE_RISK = 'CONSERVATIVE_RISK'
    NEUTRAL_RISK = 'NEUTRAL_RISK'
    AGGRESSIVE_RISK = 'AGGRESSIVE_RISK'
    PORTFOLIO_MANAGER = 'PORTFOLIO_MANAGER'

@dataclass
class DebateRound:
    round_number: int
    bull_argument: str
    bear_argument: str
    risk_consensus: str

@dataclass
class TradingAgentsDecision:
    action: str
    confidence: float
    bull_score: float
    bear_score: float
    risk_score: float
    debate_history: List[DebateRound]
    reasoning: str

class BullResearcherAgent:
    """Bullish Thesis & Upside Catalyst Evaluator."""

    def evaluate(self, symbol: str, technical_score: float, fundamental_score: float, sentiment_score: float) -> Tuple[float, str]:
        upside = technical_score * 0.3 + fundamental_score * 0.4 + sentiment_score * 0.3
        thesis = f'Bull Thesis ({symbol}): Strong growth catalysts, favorable risk-reward, composite score = {upside:.2f}'
        return (upside, thesis)

class BearResearcherAgent:
    """Bearish Thesis & Downside Risk Evaluator."""

    def evaluate(self, symbol: str, volatility: float, drawdown_pct: float, overbought_score: float) -> Tuple[float, str]:
        downside = volatility * 0.35 + drawdown_pct * 0.35 + overbought_score * 0.3
        thesis = f'Bear Thesis ({symbol}): Heightened downside risk, market saturation, composite risk = {downside:.2f}'
        return (downside, thesis)

class RiskDebaterAgent:
    """Risk Triad Evaluator (Conservative, Neutral, Aggressive)."""

    def evaluate(self, bull_score: float, bear_score: float) -> Tuple[float, str]:
        risk_balance = bull_score - bear_score
        if risk_balance > 0.2:
            return (0.85, 'Conservative & Neutral Risk: Low downside exposure, greenlight trade.')
        elif risk_balance < -0.2:
            return (0.15, 'Aggressive Risk: Downside risk dominates, veto entry.')
        return (0.5, 'Neutral Risk: Balanced bull/bear forces, caution advised.')

class TradingAgentsOrchestrator:
    """Multi-Agent Swarm Debate & Portfolio Decision Synthesizer."""

    def __init__(self) -> None:
        self.bull_agent = BullResearcherAgent()
        self.bear_agent = BearResearcherAgent()
        self.risk_agent = RiskDebaterAgent()

    def run_debate_and_synthesize(self, symbol: str, technical_score: float=0.7, fundamental_score: float=0.8, sentiment_score: float=0.75, volatility: float=0.2, drawdown_pct: float=0.15, overbought_score: float=0.3, rounds: int=2) -> TradingAgentsDecision:
        """Executes iterative Bull vs. Bear debate rounds and synthesizes final trade action."""
        debate_history: List[DebateRound] = []
        bull_score, bull_thesis = self.bull_agent.evaluate(symbol, technical_score, fundamental_score, sentiment_score)
        bear_score, bear_thesis = self.bear_agent.evaluate(symbol, volatility, drawdown_pct, overbought_score)
        for r in range(1, rounds + 1):
            risk_score, risk_text = self.risk_agent.evaluate(bull_score, bear_score)
            debate_history.append(DebateRound(round_number=r, bull_argument=f'Round {r}: {bull_thesis}', bear_argument=f'Round {r}: {bear_thesis}', risk_consensus=f'Round {r}: {risk_text}'))
        action = 'HOLD'
        confidence = 0.5
        if bull_score > bear_score + 0.15:
            action = 'BUY'
            confidence = min(0.95, 0.5 + (bull_score - bear_score))
        elif bear_score > bull_score + 0.15:
            action = 'SELL'
            confidence = min(0.95, 0.5 + (bear_score - bull_score))
        reasoning = f'Debate completed ({rounds} rounds). Bull Score: {bull_score:.2f}, Bear Score: {bear_score:.2f}. Decision: {action}'
        return TradingAgentsDecision(action=action, confidence=confidence, bull_score=bull_score, bear_score=bear_score, risk_score=risk_score, debate_history=debate_history, reasoning=reasoning)
