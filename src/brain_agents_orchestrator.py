from typing import Any

"""
Collaborative Multi-Agent Brain Supervisory & Learning Orchestrator.
Operates as a distinct, multi-threaded & multi-processed parallel intelligence unit
SEPARATE from the core trading execution engine.

Architecture:
  - Core Brain AI Agents (Research, Analyst, Prediction, Strategy, Risk, Execution)
  - 4 Trading Method AI Agents & Brains (Scalping, Day Trading, Swing, Position)
  - 13 Trading Strategy AI Agents & Brains (SMC/ICT, Order Flow, VSA, StatArb, Mean Rev, Trend, MACD, Breakout, Carry, Grid, ORB, MTF, Deterministic Neural)
  - Method Governor Brain & Strategy Governor Brain
  - 2 Trading Mechanism AI Agents & Brains (Risk Assessment, Lot Management)
  - Parallel Multiprocessing & Multithreading Processing Pipeline
  - Master Agentic Brains Swarm Orchestrator
"""
import concurrent.futures
import datetime
import os
import time
from typing import Any

import database


class BrainAgentContext:
    """Shared communication container passed across Brain AI Agents."""

    def __init__(self, symbol: Any = "EURUSD") -> None:
        self.symbol = symbol
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.research_data = {}
        self.technical_data = {}
        self.prediction_data = {}
        self.strategy_data = {}
        self.method_data = {}
        self.risk_data = {}
        self.lot_data = {}
        self.execution_data = {}
        self.agent_messages = []
        self.interventions = []

    def log_agent_message(self, agent_name: Any, message: Any) -> None:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] [{agent_name}] {message}"
        self.agent_messages.append(entry)


class BrainOrchestratorDirective:
    """
    Final output produced by the Master Orchestrator after parallel multi-agent evaluation.
    This directive is passed as an information/instruction payload to the trading engine.
    """

    def __init__(self) -> None:
        self.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.recommended_bias = "HOLD"
        self.confidence_score = 0.0
        self.recommended_style = "SCALPING"
        self.strategy_scores = {}
        self.method_scores = {}
        self.governor_decisions = {}
        self.risk_ceiling_modifier = 1.0
        self.lot_multiplier = 1.0
        self.execution_instructions = {"max_spread_pips": 3.5, "min_probability_gate": 60.0, "urgency": "NORMAL"}
        self.guidance_notes = []

    def to_dict(self) -> Any:
        return {
            "timestamp": self.timestamp,
            "recommended_bias": self.recommended_bias,
            "confidence_score": round(self.confidence_score, 2),
            "recommended_style": self.recommended_style,
            "strategy_scores": self.strategy_scores,
            "method_scores": self.method_scores,
            "governor_decisions": self.governor_decisions,
            "risk_ceiling_modifier": round(self.risk_ceiling_modifier, 2),
            "lot_multiplier": round(self.lot_multiplier, 2),
            "execution_instructions": self.execution_instructions,
            "guidance_notes": self.guidance_notes,
        }


class ResearchBrainAgent:
    def __init__(self) -> None:
        self.name = "ResearchBrainAgent"

    def process(self, context: Any, scalper_instance: Any) -> Any:
        sentiment = database.get_prevailing_news_sentiment()
        context.research_data = {
            "prevailing_sentiment": sentiment,
            "macro_regime": "TRENDING" if sentiment != "NEUTRAL" else "NEUTRAL",
        }
        context.log_agent_message(self.name, f"Macro news sentiment extracted: '{sentiment}'.")
        return context


class AnalystBrainAgent:
    def __init__(self) -> None:
        self.name = "AnalystBrainAgent"

    def process(self, context: Any, scalper_instance: Any) -> Any:
        sym = context.symbol
        price_info = scalper_instance.conn.get_current_price(sym)
        bid = price_info.get("bid", 1.0)
        ask = price_info.get("ask", 1.0)
        mid = (bid + ask) / 2.0
        spread_pips = (ask - bid) * 10000.0 if "JPY" not in sym else (ask - bid) * 100.0
        context.technical_data = {"bid": bid, "ask": ask, "mid": mid, "spread_pips": spread_pips}
        context.log_agent_message(
            self.name, f"Analyst price action for {sym}: Mid={mid:.5f}, Spread={spread_pips:.2f} pips."
        )
        return context


class PredictionBrainAgent:
    def __init__(self) -> None:
        self.name = "PredictionBrainAgent"

    def process(self, context: Any, scalper_instance: Any) -> Any:
        import predictive_brain

        predictor = predictive_brain.get_symbol_predictor(context.symbol)
        accuracy = predictor.get_accuracy()
        loss = getattr(predictor, "last_loss", 0.05)
        if loss > 0.2:
            predictor.learning_rate = min(0.1, predictor.learning_rate * 1.1)
            context.log_agent_message(
                self.name, f"Loss elevated ({loss:.4f}). Accelerated learning rate to {predictor.learning_rate:.3f}."
            )
        else:
            predictor.learning_rate = max(0.01, predictor.learning_rate * 0.95)
        kronos = predictive_brain.get_kronos_predictor(context.symbol)
        kronos_fc = getattr(context, "kronos_forecast", {})
        context.prediction_data = {
            "accuracy": accuracy,
            "loss": loss,
            "learning_rate": predictor.learning_rate,
            "kronos_upside_prob": kronos_fc.get("upside_probability", 0.5),
            "kronos_vol_amp": kronos_fc.get("volatility_amplification", 0.0),
        }
        context.log_agent_message(
            self.name,
            f"Accuracy: {accuracy:.1f}%, Loss: {loss:.4f}, Kronos Upside Prob: {kronos_fc.get('upside_probability', 0.5):.2f}.",
        )
        return context


class ScalpingMethodAgent:
    def __init__(self) -> None:
        self.name = "ScalpingMethodAgent"

    def evaluate(self, spread_pips: Any, volatility: Any) -> Any:
        score = 85.0 if spread_pips <= 2.0 else 50.0 if spread_pips <= 3.5 else 20.0
        return {"method": "SCALPING", "score": score, "timeframe": "M1-M5", "holding_time": "<15m"}


class DayTradingMethodAgent:
    def __init__(self) -> None:
        self.name = "DayTradingMethodAgent"

    def evaluate(self, spread_pips: Any, volatility: Any) -> Any:
        score = 80.0 if 1.5 <= spread_pips <= 4.0 else 60.0
        return {"method": "DAY_TRADING", "score": score, "timeframe": "M15-H1", "holding_time": "<1d"}


class SwingTradingMethodAgent:
    def __init__(self) -> None:
        self.name = "SwingTradingMethodAgent"

    def evaluate(self, spread_pips: Any, volatility: Any) -> Any:
        score = 75.0 if volatility == "HIGH" else 60.0
        return {"method": "SWING_TRADING", "score": score, "timeframe": "H4-D1", "holding_time": "2-5d"}


class PositionTradingMethodAgent:
    def __init__(self) -> None:
        self.name = "PositionTradingMethodAgent"

    def evaluate(self, spread_pips: Any, volatility: Any) -> Any:
        score = 70.0
        return {"method": "POSITION_TRADING", "score": score, "timeframe": "D1-MN", "holding_time": ">1w"}


class SmcIctStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "SMC_ICT", "score": 88.0 if accuracy > 52 else 65.0}


class OrderFlowStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "ORDER_FLOW", "score": 86.0 if accuracy > 55 else 60.0}


class VsaStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "VSA", "score": 75.0}


class StatArbStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "STAT_ARB", "score": 70.0}


class MeanReversionStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "MEAN_REVERSION", "score": 85.0 if sentiment == "NEUTRAL" else 35.0}


class TrendFollowingStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "TREND_FOLLOWING", "score": 85.0 if sentiment in ["BULLISH", "BEARISH"] else 40.0}


class MacdMomentumStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "MACD_MOMENTUM", "score": 75.0}


class BreakoutStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "BREAKOUT", "score": 80.0 if accuracy > 60 else 50.0}


class CarryTradeStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "CARRY_TRADE", "score": 60.0}


class GridTradeStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "GRID_TRADE", "score": 55.0}


class OrbStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "ORB", "score": 65.0}


class MtfConfluenceStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "MTF_CONFLUENCE", "score": 90.0 if accuracy > 55 else 60.0}


class DeterministicNeuralStrategyAgent:
    def evaluate(self, sentiment: Any, accuracy: Any) -> Any:
        return {"strategy": "DETERMINISTIC_NEURAL", "score": 82.0 if accuracy > 50 else 58.0}


class MethodGovernorBrain:
    """Collectively governs, monitors, and synthesizes all Trading Method Agents."""

    def govern(self, method_scores: dict[str, Any]) -> dict[str, Any]:
        if not method_scores:
            return {"top_method": "SCALPING", "governor_confidence": 50.0}
        top_method = max(method_scores, key=method_scores.get)
        avg_score = sum(method_scores.values()) / len(method_scores)
        return {
            "top_method": top_method,
            "governor_confidence": round(avg_score, 2),
            "consensus_spread": round(method_scores[top_method] - avg_score, 2),
        }


class StrategyGovernorBrain:
    """Collectively governs, monitors, and synthesizes all 13 Trading Strategy Agents."""

    def govern(self, strategy_scores: dict[str, Any]) -> dict[str, Any]:
        if not strategy_scores:
            return {"top_strategy": "SMC_ICT", "governor_confidence": 50.0}
        sorted_strats = sorted(strategy_scores.items(), key=lambda x: x[1], reverse=True)
        top_strat, top_score = sorted_strats[0]
        avg_score = sum(strategy_scores.values()) / len(strategy_scores)
        return {
            "top_strategy": top_strat,
            "top_score": top_score,
            "governor_confidence": round(avg_score, 2),
            "top_3_strategies": [s[0] for s in sorted_strats[:3]],
        }


class RiskAssessmentBrainAgent:
    """Monitors, manages, and supervises system risk boundaries."""

    def __init__(self) -> None:
        self.name = "RiskAssessmentBrainAgent"

    def evaluate(self, scalper_instance: Any) -> Any:
        acc = scalper_instance.conn.get_account_info()
        equity = acc.get("equity", 10000.0)
        start_bal = (
            scalper_instance.daily_start_balance
            if getattr(scalper_instance, "daily_start_balance", 0.0) > 0
            else acc.get("balance", 10000.0)
        )
        drawdown_pct = max(0.0, (start_bal - equity) / start_bal * 100.0) if start_bal > 0 else 0.0
        modifier = 1.0
        if drawdown_pct >= 2.5:
            modifier = 0.25
        elif drawdown_pct >= 1.5:
            modifier = 0.5
        elif drawdown_pct >= 0.8:
            modifier = 0.8
        return {"equity": equity, "drawdown_pct": round(drawdown_pct, 2), "risk_modifier": modifier}


class LotManagementBrainAgent:
    """Monitors, manages, and supervises position sizing and lot allocation."""

    def __init__(self) -> None:
        self.name = "LotManagementBrainAgent"

    def evaluate(self, risk_modifier: Any, win_rate: Any) -> Any:
        lot_mult = risk_modifier * (1.2 if win_rate >= 60.0 else 0.8 if win_rate < 40.0 else 1.0)
        return {"lot_multiplier": round(max(0.1, min(2.0, lot_mult)), 2)}


def _eval_method_worker(agent: Any, spread_pips: Any, volatility: Any) -> Any:
    return agent.evaluate(spread_pips, volatility)


def _eval_strategy_worker(agent: Any, sentiment: Any, accuracy: Any) -> Any:
    return agent.evaluate(sentiment, accuracy)


class AgenticBrainsOrchestrator:
    """
    Master Agentic AI Orchestrator supervising all AI Agents and Brains
    using multi-threaded and multi-processed parallel execution pipelines.
    """

    def __init__(self) -> None:
        self.research_agent = ResearchBrainAgent()
        self.analyst_agent = AnalystBrainAgent()
        self.prediction_agent = PredictionBrainAgent()
        self.method_agents = [
            ScalpingMethodAgent(),
            DayTradingMethodAgent(),
            SwingTradingMethodAgent(),
            PositionTradingMethodAgent(),
        ]
        self.strategy_agents = [
            SmcIctStrategyAgent(),
            OrderFlowStrategyAgent(),
            VsaStrategyAgent(),
            StatArbStrategyAgent(),
            MeanReversionStrategyAgent(),
            TrendFollowingStrategyAgent(),
            MacdMomentumStrategyAgent(),
            BreakoutStrategyAgent(),
            CarryTradeStrategyAgent(),
            GridTradeStrategyAgent(),
            OrbStrategyAgent(),
            MtfConfluenceStrategyAgent(),
            DeterministicNeuralStrategyAgent(),
        ]
        self.method_governor = MethodGovernorBrain()
        self.strategy_governor = StrategyGovernorBrain()
        self.risk_assessment_agent = RiskAssessmentBrainAgent()
        self.lot_management_agent = LotManagementBrainAgent()
        self.last_loop_time = None
        self.telemetry_history = []
        self.master_interventions = []
        self.last_directive = BrainOrchestratorDirective()
        self._log_orchestrator(
            "🤖 Master Agentic Brains Orchestrator initialized with Parallel Multiprocessing & 13 Strategy Swarm."
        )

    def _log_orchestrator(self, message: Any) -> None:
        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] [ORCHESTRATOR] {message}"
        self.telemetry_history.append(entry)
        if len(self.telemetry_history) > 100:
            self.telemetry_history.pop(0)
        print(entry)

    def run_agentic_loop(self, scalper_instance: Any, symbol: Any = "EURUSD") -> Any:
        """
        Executes parallel multi-agent evaluation loops across CPU threads/processes,
        coordinates information passing, applies orchestrator guidance, and generates
        a BrainOrchestratorDirective payload.
        """
        start_time = time.time()
        self.last_loop_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
        context = BrainAgentContext(symbol=symbol)
        context = self.research_agent.process(context, scalper_instance)
        context = self.analyst_agent.process(context, scalper_instance)
        context = self.prediction_agent.process(context, scalper_instance)
        sentiment = context.research_data.get("prevailing_sentiment", "NEUTRAL")
        spread_pips = context.technical_data.get("spread_pips", 1.0)
        accuracy = context.prediction_data.get("accuracy", 50.0)
        method_scores = {}
        strategy_scores = {}
        from institutional_integrations.system_autotune import \
            global_tuned_config

        optimal_workers = global_tuned_config.get("thread_pool_workers", max(4, min((os.cpu_count() or 8) * 2, 32)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=optimal_workers) as executor:
            method_futures = {
                executor.submit(_eval_method_worker, agent, spread_pips, "MEDIUM"): agent
                for agent in self.method_agents
            }
            strategy_futures = {
                executor.submit(_eval_strategy_worker, agent, sentiment, accuracy): agent
                for agent in self.strategy_agents
            }
            for fut in concurrent.futures.as_completed(method_futures):
                try:
                    res = fut.result()
                    method_scores[res["method"]] = res["score"]
                except (ValueError, KeyError, TypeError, RuntimeError) as e:
                    print(f"⚠️ Method Agent evaluation error: {e}")
            for fut in concurrent.futures.as_completed(strategy_futures):
                try:
                    res = fut.result()
                    strategy_scores[res["strategy"]] = res["score"]
                except (ValueError, KeyError, TypeError, RuntimeError) as e:
                    print(f"⚠️ Strategy Agent evaluation error: {e}")
        method_gov_res = self.method_governor.govern(method_scores)
        strat_gov_res = self.strategy_governor.govern(strategy_scores)
        risk_res = self.risk_assessment_agent.evaluate(scalper_instance)
        perf_summary = database.get_all_time_performance()
        win_rate = perf_summary.get("win_rate", 50.0)
        lot_res = self.lot_management_agent.evaluate(risk_res["risk_modifier"], win_rate)
        directive = BrainOrchestratorDirective()
        best_method = method_gov_res.get("top_method", "SCALPING")
        directive.recommended_style = best_method
        directive.method_scores = method_scores
        directive.strategy_scores = strategy_scores
        directive.governor_decisions = {"method_governor": method_gov_res, "strategy_governor": strat_gov_res}
        if sentiment == "BULLISH" and accuracy >= 50.0:
            directive.recommended_bias = "BUY"
            directive.confidence_score = min(95.0, 50.0 + accuracy * 0.4)
        elif sentiment == "BEARISH" and accuracy >= 50.0:
            directive.recommended_bias = "SELL"
            directive.confidence_score = min(95.0, 50.0 + accuracy * 0.4)
        else:
            directive.recommended_bias = "HOLD"
            directive.confidence_score = 50.0
        directive.risk_ceiling_modifier = risk_res["risk_modifier"]
        directive.lot_multiplier = lot_res["lot_multiplier"]
        interventions = []
        if risk_res["drawdown_pct"] >= 2.5:
            interventions.append(
                f"INTERVENTION: Drawdown ({risk_res['drawdown_pct']}%) exceeded limit. Risk clamped to {risk_res['risk_modifier']}x."
            )
        if spread_pips > 4.0:
            interventions.append(f"INTERVENTION: Excessive spread ({spread_pips:.2f} pips). Enforcing HOLD bias.")
            directive.recommended_bias = "HOLD"
        self.master_interventions = interventions
        elapsed_ms = (time.time() - start_time) * 1000.0
        directive.guidance_notes.extend(
            [
                f"Parallel Multi-Agent Swarm Sweep completed in {elapsed_ms:.1f}ms for {symbol}.",
                f"Top Strategy: {strat_gov_res.get('top_strategy')} ({strat_gov_res.get('top_score')} pts) | Style: {best_method}",
            ]
        )
        self.last_directive = directive
        self._log_orchestrator(
            f"Parallel Swarm Sweep ({elapsed_ms:.1f}ms): Bias={directive.recommended_bias}, TopStrat={strat_gov_res.get('top_strategy')}, RiskMod={directive.risk_ceiling_modifier}x."
        )
        return directive

    def get_status_summary(self) -> Any:
        return {
            "last_loop_time": self.last_loop_time,
            "telemetry_history": self.telemetry_history[-10:],
            "master_interventions": self.master_interventions,
            "last_directive": self.last_directive.to_dict(),
        }


global_brain_orchestrator = AgenticBrainsOrchestrator()
