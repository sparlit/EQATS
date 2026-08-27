"""
Institutional FinAgent & Hedge Fund Agentic Swarm Engine.
Adapted from Fincept Terminal hedgeFundAgents and finagent_core (ft.txt).
Implements multi-persona hedge fund teams (Medallion Fund, Quant Research, Risk, Execution),
deliberation workflows, decision memory, signal validation, and risk guardrails.
"""

import logging
from typing import Dict, List, Any, Optional

_log = logging.getLogger(__name__)


class AgentPersona:
    """
    Represents an institutional hedge fund agent persona (e.g., Portfolio Manager, Quant Researcher, Risk Quant).
    """

    def __init__(self, name: str, role: str, expertise: List[str], risk_tolerance: float = 0.5):
        self.name = name
        self.role = role
        self.expertise = expertise
        self.risk_tolerance = max(0.0, min(1.0, risk_tolerance))

    def evaluate_signal(self, symbol: str, market_data: Dict[str, Any], signal_bias: float) -> Dict[str, Any]:
        """
        Evaluates a market signal through the perspective of the agent's persona.
        """
        volatility = market_data.get("volatility", 0.02)
        trend = market_data.get("trend", 0.0)
        spread = market_data.get("spread", 0.0002)

        adjusted_bias = signal_bias
        if self.role == "Risk Quant":
            # Risk quant dampens signals in high volatility, with risk tolerance scaling
            vol_factor = max(0.1, 1.0 - (volatility / 0.10))
            adjusted_bias *= vol_factor * (0.5 + 0.5 * self.risk_tolerance)
        elif self.role == "Quant Researcher":
            # Quant researcher incorporates trend momentum
            adjusted_bias += 0.2 * trend
        elif self.role == "Execution Trader":
            # Execution trader adjusts for spread friction
            spread_factor = max(0.1, 1.0 - (spread / 0.005))
            adjusted_bias *= spread_factor

        confidence = min(1.0, max(0.0, abs(adjusted_bias)))
        action = "BUY" if adjusted_bias > 0.2 else ("SELL" if adjusted_bias < -0.2 else "HOLD")

        return {
            "agent": self.name,
            "role": self.role,
            "action": action,
            "adjusted_bias": float(adjusted_bias),
            "confidence": float(confidence),
            "rationale": f"Role {self.role} evaluated signal bias={signal_bias:.2f} with vol={volatility:.4f}"
        }


class InvestmentCommitteeDeliberation:
    """
    Implements multi-agent investment committee consensus and signal validation.
    Synthesizes views across Research, Risk, Execution, and Portfolio Management.
    """

    def __init__(self, personas: Optional[List[AgentPersona]] = None):
        if personas:
            self.personas = personas
        else:
            self.personas = [
                AgentPersona("Medallion PM", "Portfolio Manager", ["Macro", "Multi-Asset"], risk_tolerance=0.7),
                AgentPersona("Alpha Researcher", "Quant Researcher", ["StatArb", "ML"], risk_tolerance=0.6),
                AgentPersona("Guardian Risk", "Risk Quant", ["VaR", "Drawdown"], risk_tolerance=0.5),
                AgentPersona("Microstructure Trader", "Execution Trader", ["OrderFlow", "VWAP"], risk_tolerance=0.5)
            ]

    def deliberate(self, symbol: str, market_data: Dict[str, Any], raw_signal: float) -> Dict[str, Any]:
        """
        Conducts a consensus voting round across all committee members.
        """
        evaluations = [p.evaluate_signal(symbol, market_data, raw_signal) for p in self.personas]

        total_weight = 0.0
        weighted_bias = 0.0
        votes = {"BUY": 0, "SELL": 0, "HOLD": 0}

        for ev in evaluations:
            weight = ev["confidence"]
            weighted_bias += ev["adjusted_bias"] * weight
            total_weight += weight
            votes[ev["action"]] += 1

        consensus_bias = (weighted_bias / total_weight) if total_weight > 0 else 0.0

        # Veto check: Risk Quant vetoes if confidence drops below extreme threshold (< 0.05) or severe extreme vol
        risk_quant_ev = next((ev for ev in evaluations if ev["role"] == "Risk Quant"), None)
        is_vetoed = False
        veto_reason = ""
        if risk_quant_ev and risk_quant_ev["confidence"] < 0.05:
            is_vetoed = True
            veto_reason = "Risk Quant vetoed due to extreme risk threshold breached."

        final_action = "HOLD"
        if not is_vetoed:
            if consensus_bias > 0.25 and votes["BUY"] >= 2:
                final_action = "BUY"
            elif consensus_bias < -0.25 and votes["SELL"] >= 2:
                final_action = "SELL"

        return {
            "symbol": symbol,
            "final_action": final_action,
            "consensus_bias": float(consensus_bias),
            "is_vetoed": is_vetoed,
            "veto_reason": veto_reason,
            "committee_votes": votes,
            "agent_evaluations": evaluations
        }


class HedgeFundSwarmOrchestrator:
    """
    Unified Orchestrator managing hedge fund agent swarms and memory persistence.
    """

    def __init__(self):
        self.committee = InvestmentCommitteeDeliberation()
        self.memory_history: List[Dict[str, Any]] = []

    def process_trading_opportunity(self, symbol: str, market_data: Dict[str, Any], raw_signal: float) -> Dict[str, Any]:
        result = self.committee.deliberate(symbol, market_data, raw_signal)
        self.memory_history.append(result)
        if len(self.memory_history) > 200:
            self.memory_history.pop(0)
        return result

    def get_swarm_analytics(self) -> Dict[str, Any]:
        if not self.memory_history:
            return {"total_deliberations": 0, "buy_rate": 0.0, "veto_rate": 0.0}

        total = len(self.memory_history)
        buys = sum(1 for m in self.memory_history if m["final_action"] == "BUY")
        vetoes = sum(1 for m in self.memory_history if m["is_vetoed"])

        return {
            "total_deliberations": total,
            "buy_rate": float(buys / total),
            "veto_rate": float(vetoes / total)
        }
