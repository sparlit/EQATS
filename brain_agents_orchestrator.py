"""
Collaborative Multi-Agent Brain Supervisory & Learning Orchestrator.
Operates as a distinct unit SEPARATE from the core trading execution engine.

Architecture:
  [ResearchBrainAgent] -> [AnalystBrainAgent] -> [PredictionBrainAgent]
           │                    │                      │
           ▼                    ▼                      ▼
  [StrategyBrainAgent] -> [RiskBrainAgent] -> [ExecutionBrainAgent]
           │                    │                      │
           └────────────────────┼──────────────────────┘
                                ▼
                   [AgenticBrainsOrchestrator]
                                │ (Passes Directive)
                                ▼
                       [Trading Engine]
"""

import time
import datetime
import math
import database
import config

class BrainAgentContext:
    """Shared communication container passed sequentially across Brain AI Agents."""
    def __init__(self, symbol="EURUSD"):
        self.symbol = symbol
        self.timestamp = datetime.datetime.now().isoformat()

        # Inter-agent shared state
        self.research_data = {}
        self.technical_data = {}
        self.prediction_data = {}
        self.strategy_data = {}
        self.risk_data = {}
        self.execution_data = {}

        self.agent_messages = []
        self.interventions = []

    def log_agent_message(self, agent_name, message):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] [{agent_name}] {message}"
        self.agent_messages.append(entry)

class BrainOrchestratorDirective:
    """
    Final output produced by the Master Orchestrator after the multi-agent loop completes.
    This directive is passed as an information/instruction payload to the trading engine.
    """
    def __init__(self):
        self.timestamp = datetime.datetime.now().isoformat()
        self.recommended_bias = "HOLD"  # 'BUY', 'SELL', 'HOLD'
        self.confidence_score = 0.0     # 0.0 to 100.0%
        self.strategy_weight_adjustments = {}
        self.risk_ceiling_modifier = 1.0 # Multiplier (0.0 to 1.5)
        self.execution_instructions = {
            "max_spread_pips": 3.5,
            "min_probability_gate": 60.0,
            "urgency": "NORMAL"
        }
        self.guidance_notes = []

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "recommended_bias": self.recommended_bias,
            "confidence_score": round(self.confidence_score, 2),
            "strategy_weight_adjustments": self.strategy_weight_adjustments,
            "risk_ceiling_modifier": round(self.risk_ceiling_modifier, 2),
            "execution_instructions": self.execution_instructions,
            "guidance_notes": self.guidance_notes
        }

# ==============================================================================
# INDIVIDUAL BRAIN AI AGENTS
# ==============================================================================

class ResearchBrainAgent:
    """Monitors, manages, and assists the Research Brain."""
    def __init__(self):
        self.name = "ResearchBrainAgent"
        self.health_score = 100.0

    def process(self, context, scalper_instance):
        sentiment = database.get_prevailing_news_sentiment()
        context.research_data = {
            "prevailing_sentiment": sentiment,
            "macro_regime": "NEUTRAL" if sentiment == "NEUTRAL" else "TRENDING_MACRO"
        }
        msg = f"Extracted prevailing news macro sentiment: '{sentiment}'."
        context.log_agent_message(self.name, msg)
        return context

class AnalystBrainAgent:
    """Monitors, manages, and assists the Analyst Brain."""
    def __init__(self):
        self.name = "AnalystBrainAgent"
        self.health_score = 100.0

    def process(self, context, scalper_instance):
        sym = context.symbol
        price_info = scalper_instance.conn.get_current_price(sym)
        bid = price_info.get('bid', 1.0)
        ask = price_info.get('ask', 1.0)
        mid = (bid + ask) / 2.0

        context.technical_data = {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread_pips": (ask - bid) * 10000.0 if "JPY" not in sym else (ask - bid) * 100.0
        }
        msg = f"Analyzed price action for {sym}: Mid={mid:.5f}, Spread={context.technical_data['spread_pips']:.2f} pips."
        context.log_agent_message(self.name, msg)
        return context

class PredictionBrainAgent:
    """Monitors, manages, and assists the Prediction Brain (MLP & GPT)."""
    def __init__(self):
        self.name = "PredictionBrainAgent"
        self.health_score = 100.0

    def process(self, context, scalper_instance):
        import predictive_brain
        predictor = predictive_brain.get_symbol_predictor(context.symbol)
        accuracy = predictor.get_accuracy()
        loss = getattr(predictor, 'last_loss', 0.05)

        # Help prediction brain accelerate convergence if loss is high
        if loss > 0.20:
            predictor.learning_rate = min(0.10, predictor.learning_rate * 1.1) # Accelerate learning rate
            context.log_agent_message(self.name, f"High neural loss ({loss:.4f}) detected. Accelerated learning rate to {predictor.learning_rate:.3f}.")
        else:
            predictor.learning_rate = max(0.01, predictor.learning_rate * 0.95)

        context.prediction_data = {
            "accuracy": accuracy,
            "loss": loss,
            "learning_rate": predictor.learning_rate
        }
        context.log_agent_message(self.name, f"Prediction Brain Accuracy: {accuracy:.1f}%, Loss: {loss:.4f}.")
        return context

class StrategyBrainAgent:
    """Monitors, manages, and assists the Strategy Brain."""
    def __init__(self):
        self.name = "StrategyBrainAgent"
        self.health_score = 100.0

    def process(self, context, scalper_instance):
        sentiment = context.research_data.get("prevailing_sentiment", "NEUTRAL")
        accuracy = context.prediction_data.get("accuracy", 50.0)

        # Calculate optimal strategy weights
        weights = {
            "TREND_FOLLOWING": 1.5 if sentiment in ["BULLISH", "BEARISH"] else 0.8,
            "MEAN_REVERSION": 1.5 if sentiment == "NEUTRAL" else 0.5,
            "MTF_CONFLUENCE": 2.0 if accuracy > 60.0 else 1.0,
            "BREAKOUT": 1.2
        }

        context.strategy_data = {
            "recommended_weights": weights,
            "primary_strategy": config.ACTIVE_STRATEGY
        }
        context.log_agent_message(self.name, f"Calculated adaptive strategy weights based on sentiment ({sentiment}) & AI accuracy ({accuracy:.1f}%).")
        return context

class RiskBrainAgent:
    """Monitors, manages, and assists the Risk Brain."""
    def __init__(self):
        self.name = "RiskBrainAgent"
        self.health_score = 100.0

    def process(self, context, scalper_instance):
        acc = scalper_instance.conn.get_account_info()
        equity = acc.get('equity', 10000.0)
        start_bal = scalper_instance.daily_start_balance if scalper_instance.daily_start_balance > 0 else acc.get('balance', 10000.0)

        drawdown_pct = max(0.0, ((start_bal - equity) / start_bal) * 100.0) if start_bal > 0 else 0.0

        risk_modifier = 1.0
        if drawdown_pct >= 2.0:
            risk_modifier = 0.5  # Downscale risk by 50%
            context.log_agent_message(self.name, f"Drawdown elevated ({drawdown_pct:.2f}%). Reduced risk ceiling modifier to {risk_modifier:.2f}x.")
        else:
            context.log_agent_message(self.name, f"Risk boundaries nominal (Drawdown: {drawdown_pct:.2f}%). Risk modifier: {risk_modifier:.2f}x.")

        context.risk_data = {
            "equity": equity,
            "drawdown_pct": drawdown_pct,
            "risk_modifier": risk_modifier
        }
        return context

class ExecutionBrainAgent:
    """Monitors, manages, and assists the Execution Brain."""
    def __init__(self):
        self.name = "ExecutionBrainAgent"
        self.health_score = 100.0

    def process(self, context, scalper_instance):
        spread_pips = context.technical_data.get("spread_pips", 1.0)

        urgency = "NORMAL"
        if spread_pips > 3.0:
            urgency = "LOW_SPREAD_FILTER"
            context.log_agent_message(self.name, f"High spread ({spread_pips:.2f} pips) detected. Advising LOW urgency execution filter.")
        else:
            context.log_agent_message(self.name, f"Execution conditions optimal (Spread: {spread_pips:.2f} pips).")

        context.execution_data = {
            "spread_pips": spread_pips,
            "urgency": urgency
        }
        return context

# ==============================================================================
# MASTER AGENTIC AI ORCHESTRATOR
# ==============================================================================

class AgenticBrainsOrchestrator:
    """
    Master Agentic AI Orchestrator that supervises, manages, and coordinates all
    6 Brain AI Agents in a continuous collaborative loop, intervening when necessary
    and outputting a consolidated BrainOrchestratorDirective for the trading engine.
    """

    def __init__(self):
        self.research_agent = ResearchBrainAgent()
        self.analyst_agent = AnalystBrainAgent()
        self.prediction_agent = PredictionBrainAgent()
        self.strategy_agent = StrategyBrainAgent()
        self.risk_agent = RiskBrainAgent()
        self.execution_agent = ExecutionBrainAgent()

        self.last_loop_time = None
        self.telemetry_history = []
        self.master_interventions = []
        self.last_directive = BrainOrchestratorDirective()

        self._log_orchestrator("🤖 Master Agentic Brains Orchestrator initialized successfully.")

    def _log_orchestrator(self, message):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] [ORCHESTRATOR] {message}"
        self.telemetry_history.append(entry)
        if len(self.telemetry_history) > 100:
            self.telemetry_history.pop(0)
        print(entry)

    def run_agentic_loop(self, scalper_instance, symbol="EURUSD"):
        """
        Runs the collaborative multi-agent loop across all 6 Brain AI Agents,
        evaluates inter-agent alignment, applies master interventions, and
        returns a refined BrainOrchestratorDirective.
        """
        self.last_loop_time = datetime.datetime.now().isoformat()
        context = BrainAgentContext(symbol=symbol)

        # 1. Sequential Collaborative Information Passing Loop
        context = self.research_agent.process(context, scalper_instance)
        context = self.analyst_agent.process(context, scalper_instance)
        context = self.prediction_agent.process(context, scalper_instance)
        context = self.strategy_agent.process(context, scalper_instance)
        context = self.risk_agent.process(context, scalper_instance)
        context = self.execution_agent.process(context, scalper_instance)

        # 2. Master Orchestrator Synthesis & Interventions
        directive = BrainOrchestratorDirective()

        macro_sent = context.research_data.get("prevailing_sentiment", "NEUTRAL")
        pred_acc = context.prediction_data.get("accuracy", 50.0)
        drawdown = context.risk_data.get("drawdown_pct", 0.0)
        spread_pips = context.execution_data.get("spread_pips", 1.0)

        # Consensus Bias Synthesis
        if macro_sent == "BULLISH" and pred_acc >= 55.0:
            directive.recommended_bias = "BUY"
            directive.confidence_score = min(95.0, 50.0 + pred_acc * 0.5)
        elif macro_sent == "BEARISH" and pred_acc >= 55.0:
            directive.recommended_bias = "SELL"
            directive.confidence_score = min(95.0, 50.0 + pred_acc * 0.5)
        else:
            directive.recommended_bias = "HOLD"
            directive.confidence_score = 50.0

        directive.strategy_weight_adjustments = context.strategy_data.get("recommended_weights", {})
        directive.risk_ceiling_modifier = context.risk_data.get("risk_modifier", 1.0)
        directive.execution_instructions["max_spread_pips"] = min(5.0, max(2.0, spread_pips * 1.5))

        # Master Intervention Logic
        interventions = []
        if drawdown >= 2.5:
            interventions.append(f"INTERVENTION: Elevated drawdown ({drawdown:.2f}%). Clamping risk modifier to 0.25x.")
            directive.risk_ceiling_modifier = 0.25
            directive.guidance_notes.append("Risk Brain Agent overridden by Orchestrator due to drawdown limits.")

        if spread_pips > 4.0:
            interventions.append(f"INTERVENTION: Excessive spread ({spread_pips:.2f} pips). Vetoing trade entries.")
            directive.recommended_bias = "HOLD"
            directive.guidance_notes.append("Execution Brain Agent requested spread lockout.")

        self.master_interventions = interventions
        for item in interventions:
            self._log_orchestrator(item)

        directive.guidance_notes.extend([
            f"Multi-Agent Collaborative Loop Completed for {symbol}.",
            f"Prevailing Macro: {macro_sent} | AI Accuracy: {pred_acc:.1f}% | Risk Modifier: {directive.risk_ceiling_modifier:.2f}x"
        ])

        self.last_directive = directive
        self._log_orchestrator(f"Generated Directive: Bias={directive.recommended_bias}, Confidence={directive.confidence_score:.1f}%, RiskMod={directive.risk_ceiling_modifier:.2f}x.")

        return directive

    def get_status_summary(self):
        return {
            "last_loop_time": self.last_loop_time,
            "telemetry_history": self.telemetry_history[-10:],
            "master_interventions": self.master_interventions,
            "last_directive": self.last_directive.to_dict()
        }

# Singleton Global Agentic Brains Orchestrator Instance
global_brain_orchestrator = AgenticBrainsOrchestrator()
