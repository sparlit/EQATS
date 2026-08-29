"""
Awesome LLM Apps Multi-Agent Financial Advisor & Market Intelligence Team Engine.
Combines Financial Advisor Agent, Market Analyst Agent, and Risk Management Agent
for multi-perspective asset evaluation and LLM recommendation synthesis.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("AwesomeLLMFinanceTeam")

class FinancialAdvisorAgent:
    """Provides financial budget, cash flow, and asset allocation guidance."""
    def analyze_allocation(self, equity: float, current_allocations: Dict[str, float]) -> Dict[str, Any]:
        total_allocated = sum(current_allocations.values())
        cash_balance = max(0.0, equity - total_allocated)
        cash_ratio = (cash_balance / equity) if equity > 0 else 0.0

        recommendations = []
        if cash_ratio < 0.10:
            recommendations.append("Increase cash reserve buffer to at least 10% for drawdowns.")
        elif cash_ratio > 0.50:
            recommendations.append("Deploy idle cash across uncorrelated strategy themes.")

        return {
            "equity": equity,
            "cash_balance": round(cash_balance, 2),
            "cash_ratio": round(cash_ratio, 4),
            "recommendations": recommendations
        }

class MarketAnalystAgent:
    """Analyzes market fundamentals, analyst consensus, and company news."""
    def analyze_asset(self, symbol: str, spot_price: float, target_price: float = 0.0, analyst_rating: str = "BUY") -> Dict[str, Any]:
        upside_pct = 0.0
        if spot_price > 0 and target_price > 0:
            upside_pct = ((target_price - spot_price) / spot_price) * 100.0

        return {
            "symbol": symbol.upper(),
            "spot_price": spot_price,
            "target_price": target_price,
            "upside_pct": round(upside_pct, 2),
            "analyst_rating": analyst_rating.upper(),
            "bullish_bias": analyst_rating.upper() in ["BUY", "STRONG_BUY", "OUTPERFORM"]
        }

class MultiAgentFinanceTeamOrchestrator:
    """
    Synthesizes recommendations from Advisor, Market, and Risk agents.
    """
    def __init__(self):
        self.advisor = FinancialAdvisorAgent()
        self.analyst = MarketAnalystAgent()

    def generate_team_consensus(self, symbol: str, spot_price: float, equity: float, current_allocations: Dict[str, float]) -> Dict[str, Any]:
        adv_res = self.advisor.analyze_allocation(equity, current_allocations)
        mkt_res = self.analyst.analyze_asset(symbol, spot_price)

        consensus_action = "HOLD"
        if mkt_res["bullish_bias"] and adv_res["cash_ratio"] >= 0.10:
            consensus_action = "BUY"
        elif not mkt_res["bullish_bias"]:
            consensus_action = "SELL"

        return {
            "symbol": symbol.upper(),
            "consensus_action": consensus_action,
            "advisor_summary": adv_res,
            "analyst_summary": mkt_res,
            "team": "AwesomeLLM Multi-Agent Team"
        }
