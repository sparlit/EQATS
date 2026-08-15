import pytest
import config
import connector
import brain
from brain_agents_orchestrator import (
    BrainAgentContext,
    BrainOrchestratorDirective,
    ResearchBrainAgent,
    AnalystBrainAgent,
    PredictionBrainAgent,
    StrategyBrainAgent,
    RiskBrainAgent,
    ExecutionBrainAgent,
    AgenticBrainsOrchestrator,
    global_brain_orchestrator
)

class DummyScalper:
    def __init__(self):
        self.conn = connector.SimulatorConnector(initial_balance=10000.0)
        self.daily_start_balance = 10000.0

def test_individual_brain_agents():
    scalper = DummyScalper()
    ctx = BrainAgentContext(symbol="EURUSD")

    research = ResearchBrainAgent()
    analyst = AnalystBrainAgent()
    prediction = PredictionBrainAgent()
    strategy = StrategyBrainAgent()
    risk = RiskBrainAgent()
    execution = ExecutionBrainAgent()

    ctx = research.process(ctx, scalper)
    assert "prevailing_sentiment" in ctx.research_data

    ctx = analyst.process(ctx, scalper)
    assert "bid" in ctx.technical_data
    assert "ask" in ctx.technical_data

    ctx = prediction.process(ctx, scalper)
    assert "accuracy" in ctx.prediction_data

    ctx = strategy.process(ctx, scalper)
    assert "recommended_weights" in ctx.strategy_data

    ctx = risk.process(ctx, scalper)
    assert "risk_modifier" in ctx.risk_data

    ctx = execution.process(ctx, scalper)
    assert "urgency" in ctx.execution_data

    assert len(ctx.agent_messages) >= 6

def test_master_orchestrator_directive_generation():
    scalper = DummyScalper()
    orchestrator = AgenticBrainsOrchestrator()

    directive = orchestrator.run_agentic_loop(scalper, symbol="EURUSD")
    assert isinstance(directive, BrainOrchestratorDirective)
    assert directive.recommended_bias in ["BUY", "SELL", "HOLD"]
    assert 0.0 <= directive.confidence_score <= 100.0
    assert 0.0 <= directive.risk_ceiling_modifier <= 1.5

    d_dict = directive.to_dict()
    assert "recommended_bias" in d_dict
    assert "risk_ceiling_modifier" in d_dict

def test_master_orchestrator_interventions():
    scalper = DummyScalper()
    scalper.daily_start_balance = 10000.0
    # Simulate equity drawdown
    scalper.conn.balance = 9700.0
    scalper.conn.equity = 9700.0 # 3% drawdown

    orchestrator = AgenticBrainsOrchestrator()
    directive = orchestrator.run_agentic_loop(scalper, symbol="EURUSD")

    # Master orchestrator should intervene and clamp risk modifier due to drawdown
    assert directive.risk_ceiling_modifier <= 0.50
    assert len(orchestrator.master_interventions) >= 1

def test_trading_engine_integration_decoupling():
    scalper_brain = brain.ScalperBrain()

    # Generate dummy bars (needs >= 210 bars)
    history_bars = []
    base_price = 1.1000
    for i in range(220):
        history_bars.append({
            'open': base_price + i * 0.0001,
            'high': base_price + i * 0.0001 + 0.0005,
            'low': base_price + i * 0.0001 - 0.0005,
            'close': base_price + i * 0.0001 + 0.0002
        })

    # Test evaluate with default directive
    res1 = scalper_brain.evaluate("EURUSD", history_bars, 10000.0)
    assert "decision" in res1
    assert "lot_size" in res1

    # Test evaluate with custom directive (50% risk modifier)
    directive = BrainOrchestratorDirective()
    directive.risk_ceiling_modifier = 0.5
    directive.guidance_notes.append("Testing custom risk modifier decoupling.")

    res2 = scalper_brain.evaluate("EURUSD", history_bars, 10000.0, brain_directive=directive)
    assert res2["lot_size"] <= res1["lot_size"]
    assert "Testing custom risk modifier decoupling" in res2["explanation"]
