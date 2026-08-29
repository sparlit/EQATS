import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("BayesianConsensusEngine")

class BayesianConsensusEngine:
    """
    V4.0-PRO: Bayesian Probability & Consensus Signal Engine.
    Aggregates multi-strategy evidence with strategy reliability weights to produce
    statistically calibrated posterior directional probabilities.
    """
    def __init__(self):
        self.symbol_state: Dict[str, Dict[str, Any]] = {}
        self.reliability: Dict[str, float] = {
            "TREND_FOLLOWING": 0.80,
            "MEAN_REVERSION": 0.75,
            "MACD_MOMENTUM": 0.70,
            "BREAKOUT": 0.75,
            "WYCKOFF_ACCUMULATION": 0.85,
            "SUPERTREND_TREND": 0.80,
            "DONCHIAN_BREAKOUT": 0.75,
            "TURTLE_BREAKOUT": 0.80,
            "RSI_MOMENTUM": 0.70,
            "ICT_KILLZONE": 0.85,
            "CARRY_TRADE": 0.85,
            "SMC_ICT": 0.85,
            "QUANT_MACHINE_LEARNING": 0.88,
        }

    def _get_state(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.symbol_state:
            self.symbol_state[symbol] = {
                "prior": 0.5,
                "evidence_history": [],
                "last_update": time.time()
            }
        return self.symbol_state[symbol]

    def set_strategy_reliability(self, strategy_name: str, reliability: float) -> None:
        self.reliability[strategy_name] = max(0.1, min(0.99, reliability))

    def update_evidence(self, symbol: str, source_strategy: str, signal: str, raw_prob: float = 0.75) -> float:
        """
        Updates Bayesian prior probability for `symbol` given evidence from `source_strategy`.
        signal: 'BUY' (p_e_h > 0.5), 'SELL' (p_e_h < 0.5), or 'HOLD' (0.5)
        Returns the updated posterior probability for BULLISH stance.
        """
        state = self._get_state(symbol)
        prior = state["prior"]

        if signal == "BUY":
            p_e_h = max(0.51, min(0.99, raw_prob))
        elif signal == "SELL":
            p_e_h = min(0.49, max(0.01, 1.0 - raw_prob))
        else:
            p_e_h = 0.5

        rel = self.reliability.get(source_strategy, 0.75)
        weighted_p_e_h = 0.5 + (p_e_h - 0.5) * rel

        # Bayesian posterior formula
        denominator = (weighted_p_e_h * prior) + ((1.0 - weighted_p_e_h) * (1.0 - prior))
        if denominator <= 1e-8:
            posterior = prior
        else:
            posterior = (weighted_p_e_h * prior) / denominator

        posterior = max(0.01, min(0.99, posterior))
        state["prior"] = posterior
        state["last_update"] = time.time()
        state["evidence_history"].append({
            "source": source_strategy,
            "signal": signal,
            "posterior": posterior,
            "ts": time.time()
        })
        return posterior

    def get_consensus_decision(self, symbol: str, buy_threshold: float = 0.75, sell_threshold: float = 0.25) -> Dict[str, Any]:
        """
        Evaluates Bayesian consensus for symbol.
        """
        state = self._get_state(symbol)
        prob = state["prior"]
        decision = "HOLD"
        if prob >= buy_threshold:
            decision = "BUY"
        elif prob <= sell_threshold:
            decision = "SELL"

        return {
            "symbol": symbol,
            "decision": decision,
            "posterior_probability": prob,
            "evidence_count": len(state["evidence_history"]),
            "last_update": state["last_update"]
        }

# Global singleton instance
global_bayesian_consensus = BayesianConsensusEngine()
