"""
AI-Trader Signal Quality & Challenge Scoring Engine (EQATS Institutional Adaptation)
Adapted from HKUDS/AI-Trader (service/server/signal_quality.py & challenge_scoring.py)

Provides:
- AITraderSignalQualityEvaluator: Signal directional accuracy %, Expected Sharpe, Drawdown impact, and Composite Signal Quality Score
- AITraderChallengeScoringEngine: Multi-agent trade scoring, risk-adjusted score formula, max position size compliance, disqualification auditor, and leaderboard ranker
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class SignalQualityMetrics:
    directional_accuracy_pct: float
    expected_sharpe: float
    drawdown_impact_pct: float
    composite_quality_score: float
    grade: str


@dataclass
class AgentScoreResult:
    agent_id: str
    starting_cash: float
    ending_value: float
    return_pct: float
    max_drawdown_pct: float
    risk_adjusted_score: float
    final_score: float | None
    trade_count: int
    disqualified_reason: str | None
    rank: int | None = None


class AITraderSignalQualityEvaluator:
    """Evaluates AI & Agent Trade Signal Quality prior to live execution."""

    def evaluate_signal_quality(
        self, historical_signals: list[dict[str, Any]], historical_returns: list[float],
    ) -> SignalQualityMetrics:
        """Calculates Directional Accuracy %, Expected Sharpe, Drawdown Impact, and Composite Quality Score."""
        if not historical_signals or not historical_returns or len(historical_signals) != len(historical_returns):
            return SignalQualityMetrics(0.0, 0.0, 0.0, 0.0, "F")
        correct_dirs = 0
        for sig, ret in zip(historical_signals, historical_returns):
            direction = sig.get("direction", "BUY").upper()
            if (direction in ("BUY", "LONG") and ret > 0) or (direction in ("SELL", "SHORT") and ret < 0):
                correct_dirs += 1
        acc_pct = correct_dirs / float(len(historical_signals)) * 100.0
        ret_arr = np.array(historical_returns)
        mean_ret = float(np.mean(ret_arr))
        std_ret = float(np.std(ret_arr, ddof=1)) if len(ret_arr) > 1 else 1e-06
        sharpe = mean_ret / (std_ret + 1e-06) * math.sqrt(252)
        cum_equity = np.cumsum(ret_arr)
        peak = np.maximum.accumulate(cum_equity)
        dd = peak - cum_equity
        max_dd_pct = float(np.max(dd)) * 100.0 if len(dd) > 0 else 0.0
        acc_component = min(1.0, acc_pct / 100.0) * 0.4
        sharpe_component = min(1.0, max(0.0, sharpe / 3.0)) * 0.4
        dd_component = max(0.0, 1.0 - max_dd_pct / 20.0) * 0.2
        composite_score = round(acc_component + sharpe_component + dd_component, 2)
        grade = (
            "A+"
            if composite_score >= 0.85
            else "A"
            if composite_score >= 0.7
            else "B"
            if composite_score >= 0.55
            else "C"
            if composite_score >= 0.4
            else "F"
        )
        return SignalQualityMetrics(
            directional_accuracy_pct=round(acc_pct, 1),
            expected_sharpe=round(sharpe, 2),
            drawdown_impact_pct=round(max_dd_pct, 2),
            composite_quality_score=composite_score,
            grade=grade,
        )


class AITraderChallengeScoringEngine:
    """Multi-Agent Challenge Scoring & Leaderboard Ranker Engine."""

    def __init__(
        self,
        allowed_drawdown_pct: float = 5.0,
        drawdown_penalty: float = 1.0,
        max_position_pct: float = 25.0,
        max_drawdown_pct: float = 10.0,
    ) -> None:
        self.allowed_drawdown_pct = allowed_drawdown_pct
        self.drawdown_penalty = drawdown_penalty
        self.max_position_pct = max_position_pct
        self.max_drawdown_pct = max_drawdown_pct

    def score_agent_trades(self, agent_id: str, starting_cash: float, trades: list[dict[str, Any]]) -> AgentScoreResult:
        """Scores an individual agent's trades, tracks drawdown & position limits, and computes risk-adjusted returns."""
        cash = starting_cash
        positions: dict[str, dict[str, Any]] = {}
        equity_curve = [starting_cash]
        peak = starting_cash
        max_dd_pct = 0.0
        disqualified_reason = None
        for t in trades:
            if disqualified_reason:
                break
            symbol = t.get("symbol", "UNKNOWN")
            side = t.get("side", "BUY").upper()
            price = float(t.get("price", 0.0))
            qty = float(t.get("quantity", 0.0))
            if price <= 0 or qty <= 0:
                disqualified_reason = f"invalid_trade_data:{symbol}"
                break
            curr_qty = positions.get(symbol, {}).get("quantity", 0.0)
            if side == "BUY":
                cash -= price * qty
                new_qty = curr_qty + qty
                positions[symbol] = {"symbol": symbol, "quantity": new_qty, "entry_price": price}
            elif side == "SELL":
                if curr_qty < qty:
                    disqualified_reason = f"sell_exceeds_position:{symbol}"
                    break
                cash += price * qty
                new_qty = curr_qty - qty
                if new_qty <= 1e-09:
                    positions.pop(symbol, None)
                else:
                    positions[symbol]["quantity"] = new_qty
            port_val = cash + sum(pos["quantity"] * pos["entry_price"] for pos in positions.values())
            equity_curve.append(port_val)
            peak = max(peak, port_val)
            if peak > 0:
                dd = (peak - port_val) / peak * 100.0
                max_dd_pct = max(max_dd_pct, dd)
            if self.max_position_pct > 0 and port_val > 0 and positions:
                max_pos_val = max(p["quantity"] * p["entry_price"] for p in positions.values())
                if max_pos_val / port_val * 100.0 > self.max_position_pct + 1e-06:
                    disqualified_reason = "max_position_pct_exceeded"
                    break
        ending_value = cash + sum(pos["quantity"] * pos["entry_price"] for pos in positions.values())
        return_pct = (ending_value - starting_cash) / starting_cash * 100.0 if starting_cash > 0 else 0.0
        if self.max_drawdown_pct > 0 and max_dd_pct > self.max_drawdown_pct + 1e-06:
            disqualified_reason = disqualified_reason or "max_drawdown_pct_exceeded"
        risk_adjusted_score = return_pct - max(0.0, max_dd_pct - self.allowed_drawdown_pct) * self.drawdown_penalty
        final_score = None if disqualified_reason or not trades else risk_adjusted_score
        return AgentScoreResult(
            agent_id=agent_id,
            starting_cash=starting_cash,
            ending_value=round(ending_value, 2),
            return_pct=round(return_pct, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            risk_adjusted_score=round(risk_adjusted_score, 2),
            final_score=round(final_score, 2) if final_score is not None else None,
            trade_count=len(trades),
            disqualified_reason=disqualified_reason,
        )

    def rank_leaderboard(self, agent_results: list[AgentScoreResult]) -> list[AgentScoreResult]:
        """Ranks scored agent results to produce competitive leaderboard rankings."""
        valid_agents = [r for r in agent_results if not r.disqualified_reason and r.final_score is not None]
        valid_agents.sort(key=lambda r: r.final_score or -999.0, reverse=True)
        rank_map = {r.agent_id: idx + 1 for idx, r in enumerate(valid_agents)}
        results = []
        for r in agent_results:
            results.append(
                AgentScoreResult(
                    agent_id=r.agent_id,
                    starting_cash=r.starting_cash,
                    ending_value=r.ending_value,
                    return_pct=r.return_pct,
                    max_drawdown_pct=r.max_drawdown_pct,
                    risk_adjusted_score=r.risk_adjusted_score,
                    final_score=r.final_score,
                    trade_count=r.trade_count,
                    disqualified_reason=r.disqualified_reason,
                    rank=rank_map.get(r.agent_id),
                ),
            )
        return results
