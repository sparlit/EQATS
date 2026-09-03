"""
Neoethos Autonomous Quantitative Strategy & AutoResearch Engine (EQATS Institutional Adaptation)
Adapted from kosred/Neoethos (neoethos-autoresearch & neoethos-trader)

Provides:
- Reproducible Seed-Driven AutoResearch Loop
- T-Stat Objective Scoring & Cost-Edge Scoring
- In-Market Fitness Tracker & Feature Block Shuffling Experiments
- Soft-Voting Ensemble Replay Engine
"""

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class ResearchObjectiveConfig:
    t_stat_weight: float = 0.4
    cost_edge_weight: float = 0.3
    in_market_weight: float = 0.3
    min_t_stat_threshold: float = 2.0
    seed: int = 42


@dataclass
class ResearchHypothesisResult:
    hypothesis_id: str
    t_stat: float
    cost_edge_score: float
    in_market_fitness: float
    combined_score: float
    passed: bool
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class NeoethosReplayStats:
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    total_return_pct: float


class NeoethosAutoResearchEngine:
    """Neoethos Autonomous Quantitative AutoResearch & Replay Engine."""

    def __init__(self, config: ResearchObjectiveConfig | None = None) -> None:
        self.config = config or ResearchObjectiveConfig()

    def evaluate_hypothesis(
        self, returns: list[float], transaction_costs_bps: float = 2.0, hypothesis_id: str = "HYP_001",
    ) -> ResearchHypothesisResult:
        """Evaluates a quantitative strategy hypothesis using T-Stat, Cost-Edge, and In-Market Fitness."""
        if not returns or len(returns) < 5:
            return ResearchHypothesisResult(
                hypothesis_id=hypothesis_id,
                t_stat=0.0,
                cost_edge_score=0.0,
                in_market_fitness=0.0,
                combined_score=0.0,
                passed=False,
                metrics={"reason": "Insufficient return series data"},
            )
        returns_arr = np.array(returns)
        n = len(returns_arr)
        mean_ret = float(np.mean(returns_arr))
        std_ret = float(np.std(returns_arr, ddof=1)) if n > 1 else 0.0
        se = std_ret / math.sqrt(n) if std_ret > 0 else 1e-06
        t_stat = mean_ret / se if se > 0 else 0.0
        cost_per_trade = transaction_costs_bps / 10000.0
        net_returns = returns_arr - cost_per_trade
        net_mean = float(np.mean(net_returns))
        cost_edge_score = net_mean / (std_ret + 1e-06) * math.sqrt(252)
        wins = np.sum(returns_arr > 0)
        win_rate = wins / float(n)
        ann_sharpe = mean_ret / (std_ret + 1e-06) * math.sqrt(252)
        in_market_fitness = ann_sharpe * win_rate
        combined_score = (
            t_stat * self.config.t_stat_weight
            + cost_edge_score * self.config.cost_edge_weight
            + in_market_fitness * self.config.in_market_weight
        )
        passed = t_stat >= self.config.min_t_stat_threshold and cost_edge_score > 0.0
        return ResearchHypothesisResult(
            hypothesis_id=hypothesis_id,
            t_stat=t_stat,
            cost_edge_score=cost_edge_score,
            in_market_fitness=in_market_fitness,
            combined_score=combined_score,
            passed=passed,
            metrics={"mean_return": mean_ret, "std_return": std_ret, "win_rate": win_rate, "sharpe_ratio": ann_sharpe},
        )

    def run_feature_shuffle_experiment(
        self, returns: list[float], num_shuffles: int = 100, seed: int | None = None,
    ) -> dict[str, Any]:
        """Runs reproducible feature block shuffle experiments to test signal degradation against noise."""
        rng = random.Random(seed or self.config.seed)
        original_result = self.evaluate_hypothesis(returns, hypothesis_id="ORIGINAL")
        shuffled_scores = []
        returns_copy = list(returns)
        for _ in range(num_shuffles):
            rng.shuffle(returns_copy)
            res = self.evaluate_hypothesis(returns_copy, hypothesis_id="SHUFFLED")
            shuffled_scores.append(res.combined_score)
        p_value = np.sum(np.array(shuffled_scores) >= original_result.combined_score) / float(num_shuffles)
        return {
            "original_combined_score": original_result.combined_score,
            "shuffled_mean_score": float(np.mean(shuffled_scores)),
            "p_value": p_value,
            "statistically_significant": p_value < 0.05,
        }

    def run_soft_voting_ensemble_replay(
        self, strategy_signals: dict[str, list[float]], weights: dict[str, float] | None = None,
    ) -> NeoethosReplayStats:
        """Executes soft-voting ensemble signal recombination and calculates deterministic replay statistics."""
        if not strategy_signals:
            return NeoethosReplayStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
        num_bars = len(next(iter(strategy_signals.values())))
        if weights is None:
            weights = {strat: 1.0 / len(strategy_signals) for strat in strategy_signals}
        combined_returns = []
        for bar_idx in range(num_bars):
            bar_weighted_signal = sum(
                strategy_signals[strat][bar_idx] * weights.get(strat, 1.0) for strat in strategy_signals
            )
            combined_returns.append(bar_weighted_signal)
        returns_arr = np.array(combined_returns)
        total_trades = len(returns_arr)
        wins = np.sum(returns_arr > 0)
        losses = np.sum(returns_arr < 0)
        win_rate = wins / total_trades * 100.0 if total_trades > 0 else 0.0
        gross_profit = float(np.sum(returns_arr[returns_arr > 0])) if wins > 0 else 0.0
        gross_loss = float(abs(np.sum(returns_arr[returns_arr < 0]))) if losses > 0 else 1e-06
        profit_factor = gross_profit / gross_loss
        mean_ret = float(np.mean(returns_arr))
        std_ret = float(np.std(returns_arr))
        sharpe = mean_ret / (std_ret + 1e-06) * math.sqrt(252)
        cum_equity = np.cumsum(returns_arr)
        peak = np.maximum.accumulate(cum_equity)
        drawdowns = peak - cum_equity
        max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0
        tot_ret = float(np.sum(returns_arr))
        return NeoethosReplayStats(
            total_trades=total_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            total_return_pct=tot_ret,
        )
