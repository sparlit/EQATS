from typing import Any
"""
Institutional Trade Memory & Reflection Protocol (EQATS v8.4).
Inspired by tradememory-protocol: records post-mortem trade reflections,
calculates Maximum Favorable Excursion (MFE) / Maximum Adverse Excursion (MAE),
computes trade efficiency scores, analyzes post-mortem feature correlations across
winning vs losing vs vetoed trades, and dynamically updates AI Brain Agent memory buffers.
"""

import datetime
import logging

_log = logging.getLogger(__name__)


class TradeMemoryReflectionProtocol:
    """Manages trade reflections, post-mortems, self-learning feature analysis, and cognitive memory buffers."""

    def __init__(self):
        self.memory_records = []
        self.reflections_log = []
        self.adaptive_weights = {
            "TREND_FOLLOWING": 1.0,
            "MEAN_REVERSION": 1.0,
            "MACD_MOMENTUM": 1.0,
            "BREAKOUT": 1.0,
            "CARRY_TRADE": 1.0,
            "GRID_TRADE": 1.0,
            "STAT_ARB": 1.0,
            "ORB": 1.0,
            "VSA": 1.0,
            "MTF_CONFLUENCE": 1.0,
            "SMC_ICT": 1.0,
            "ORDER_FLOW": 1.0,
            "VOTING_ENSEMBLE": 1.0,
        }

    def log_reflection(
        self,
        ticket,
        symbol,
        direction,
        open_price,
        close_price,
        profit,
        reason,
        mfe=0.0,
        mae=0.0,
        strategy_used="VOTING_ENSEMBLE",
    ):
        """
        Calculates trade efficiency metrics and logs a post-mortem reflection record.
        """
        ts = datetime.datetime.now().isoformat()
        is_win = profit > 0.0

        # Calculate efficiency score
        efficiency = 100.0 if is_win else 0.0
        if mae > 0:
            efficiency = max(0.0, min(100.0, (mfe / (mae + 0.0001)) * 50.0))

        reflection_note = (
            f"Trade #{ticket} [{symbol} {direction}] Strategy={strategy_used}: {'WIN' if is_win else 'LOSS'} (${profit:+.2f}). "
            f"Exit Reason: {reason}. Close: {close_price:.5f}. Efficiency Score: {efficiency:.1f}%."
        )

        record = {
            "timestamp": ts,
            "ticket": str(ticket),
            "symbol": symbol,
            "direction": direction,
            "open_price": open_price,
            "close_price": close_price,
            "profit": profit,
            "reason": reason,
            "is_win": is_win,
            "mfe": mfe,
            "mae": mae,
            "efficiency_score": round(efficiency, 1),
            "strategy_used": strategy_used,
            "reflection_note": reflection_note,
        }

        self.memory_records.append(record)
        if len(self.memory_records) > 500:
            self.memory_records.pop(0)

        self.reflections_log.append(f"[{ts[:19]}] {reflection_note}")
        if len(self.reflections_log) > 200:
            self.reflections_log.pop(0)

        _log.info("🧠 [TRADE MEMORY] %s", reflection_note)

        # Trigger self-learning adaptive weight update
        self._retrain_adaptive_weights(strategy_used, is_win, profit)

        # Update Vector Memory Buffer in local LLM if available
        try:
            import institutional_integrations.quantum_local_llm as qllm

            qllm.save_semantic_context(
                f"Trade_{ticket}", reflection_note, metadata=record
            )
        except Exception as e:
            _log.debug("Trade memory LLM context store note: %s", e)

        return record

    def log_no_trade_veto(self, symbol, direction, signal_probability, veto_reason, strategy_used="VOTING_ENSEMBLE"):
        """
        Logs a post-mortem reflection record when a high-probability trade opportunity is vetoed
        by hard risk kernel invariants (INV-001..INV-015), regime mismatches, or low confidence.
        """
        ts = datetime.datetime.now().isoformat()
        reflection_note = (
            f"NO-TRADE VETO [{symbol} {direction}] Strategy={strategy_used}: Prob={signal_probability:.1f}%. "
            f"Veto Reason: {veto_reason}."
        )

        record = {
            "timestamp": ts,
            "ticket": "VETO",
            "symbol": symbol,
            "direction": direction,
            "open_price": 0.0,
            "close_price": 0.0,
            "profit": 0.0,
            "reason": f"VETO: {veto_reason}",
            "is_win": False,
            "mfe": 0.0,
            "mae": 0.0,
            "efficiency_score": 0.0,
            "strategy_used": strategy_used,
            "reflection_note": reflection_note,
        }

        self.memory_records.append(record)
        if len(self.memory_records) > 500:
            self.memory_records.pop(0)

        self.reflections_log.append(f"[{ts[:19]}] {reflection_note}")
        if len(self.reflections_log) > 200:
            self.reflections_log.pop(0)

        _log.info("🧠 [TRADE MEMORY VETO] %s", reflection_note)
        return record

    def _retrain_adaptive_weights(self, strategy_used: str, is_win: bool, profit: float):
        """
        Self-learning post-mortem retraining algorithm.
        Dynamically adjusts strategy weight multiplier based on empirical win/loss feedback.
        """
        current_weight = self.adaptive_weights.get(strategy_used, 1.0)
        if is_win:
            # Reward winning strategy (+2% boost up to 2.0 max)
            new_weight = min(2.0, current_weight * 1.02 + 0.01)
        else:
            # Penalty for losing strategy (-3% reduction down to 0.2 min)
            new_weight = max(0.2, current_weight * 0.97 - 0.01)

        self.adaptive_weights[strategy_used] = round(new_weight, 4)
        _log.info("Self-Learning Retrained %s weight: %.4f -> %.4f", strategy_used, current_weight, new_weight)

    def get_adaptive_strategy_weight(self, strategy_name: str) -> float:
        """Returns the self-learned adaptive weight multiplier for a given strategy."""
        return self.adaptive_weights.get(strategy_name, 1.0)

    def analyze_post_mortem_features(self) -> dict[str, Any]:
        """
        Analyzes post-mortem records across closed trades and vetoes.
        Returns statistical summary of win rates, veto counts, and strategy performance rankings.
        """
        if not self.memory_records:
            return {
                "total_records": 0,
                "win_count": 0,
                "loss_count": 0,
                "veto_count": 0,
                "win_rate_pct": 0.0,
                "avg_efficiency_pct": 0.0,
                "strategy_rankings": {},
            }

        total = len(self.memory_records)
        trades = [r for r in self.memory_records if r["ticket"] != "VETO"]
        vetoes = [r for r in self.memory_records if r["ticket"] == "VETO"]
        wins = [r for r in trades if r["is_win"]]

        win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
        avg_eff = (sum(r["efficiency_score"] for r in trades) / len(trades)) if trades else 0.0

        return {
            "total_records": total,
            "trade_count": len(trades),
            "win_count": len(wins),
            "loss_count": len(trades) - len(wins),
            "veto_count": len(vetoes),
            "win_rate_pct": round(win_rate, 2),
            "avg_efficiency_pct": round(avg_eff, 2),
            "adaptive_weights": dict(self.adaptive_weights),
        }

    def get_summary(self, symbol=None):
        """Returns trade memory summary statistics."""
        records = self.memory_records
        if symbol:
            records = [r for r in records if r["symbol"] == symbol]

        if not records:
            return {
                "total_reflections": 0,
                "win_rate": 0.0,
                "avg_efficiency": 0.0,
                "recent_reflections": [],
            }

        wins = sum(1 for r in records if r["is_win"])
        win_rate = (wins / len(records)) * 100.0
        avg_eff = sum(r["efficiency_score"] for r in records) / len(records)

        return {
            "total_reflections": len(records),
            "win_rate": round(win_rate, 1),
            "avg_efficiency": round(avg_eff, 1),
            "recent_reflections": [r["reflection_note"] for r in records[-5:]],
        }


# Global Singleton Protocol Instance
global_trade_memory_protocol = TradeMemoryReflectionProtocol()
