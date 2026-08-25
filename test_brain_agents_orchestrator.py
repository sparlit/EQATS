import brain
import connector
import database
from brain_agents_orchestrator import (
    AgenticBrainsOrchestrator,
    AnalystBrainAgent,
    BrainAgentContext,
    BrainOrchestratorDirective,
    DayTradingMethodAgent,
    LotManagementBrainAgent,
    MeanReversionStrategyAgent,
    MtfConfluenceStrategyAgent,
    PositionTradingMethodAgent,
    PredictionBrainAgent,
    ResearchBrainAgent,
    RiskAssessmentBrainAgent,
    ScalpingMethodAgent,
    SwingTradingMethodAgent,
    TrendFollowingStrategyAgent,
)



class DummyScalper:
    def __init__(self):
        database.init_db()
        self.conn = connector.SimulatorConnector(initial_balance=10000.0)
        self.daily_start_balance = 10000.0


def test_individual_brain_agents():
    scalper = DummyScalper()
    ctx = BrainAgentContext(symbol="EURUSD")

    research = ResearchBrainAgent()
    analyst = AnalystBrainAgent()
    prediction = PredictionBrainAgent()

    ctx = research.process(ctx, scalper)
    assert "prevailing_sentiment" in ctx.research_data

    ctx = analyst.process(ctx, scalper)
    assert "bid" in ctx.technical_data
    assert "ask" in ctx.technical_data

    ctx = prediction.process(ctx, scalper)
    assert "accuracy" in ctx.prediction_data

    assert len(ctx.agent_messages) >= 3


def test_trading_methods_and_strategy_agents():
    scalp = ScalpingMethodAgent().evaluate(spread_pips=1.5, volatility="MEDIUM")
    assert scalp["method"] == "SCALPING"
    assert scalp["score"] == 85.0

    day = DayTradingMethodAgent().evaluate(spread_pips=2.0, volatility="MEDIUM")
    assert day["method"] == "DAY_TRADING"

    swing = SwingTradingMethodAgent().evaluate(spread_pips=2.0, volatility="HIGH")
    assert swing["score"] == 75.0

    pos = PositionTradingMethodAgent().evaluate(spread_pips=2.0, volatility="LOW")
    assert pos["method"] == "POSITION_TRADING"

    tf = TrendFollowingStrategyAgent().evaluate(sentiment="BULLISH", accuracy=65.0)
    assert tf["score"] == 85.0

    mr = MeanReversionStrategyAgent().evaluate(sentiment="NEUTRAL", accuracy=65.0)
    assert mr["score"] == 85.0

    mtf = MtfConfluenceStrategyAgent().evaluate(sentiment="BULLISH", accuracy=65.0)
    assert mtf["score"] == 90.0


def test_trading_mechanism_risk_and_lot_agents():
    scalper = DummyScalper()
    risk_agent = RiskAssessmentBrainAgent()
    lot_agent = LotManagementBrainAgent()

    risk_res = risk_agent.evaluate(scalper)
    assert "risk_modifier" in risk_res
    assert risk_res["risk_modifier"] == 1.0

    lot_res = lot_agent.evaluate(risk_res["risk_modifier"], win_rate=65.0)
    assert "lot_multiplier" in lot_res
    assert lot_res["lot_multiplier"] >= 1.0


def test_master_orchestrator_directive_generation():
    scalper = DummyScalper()
    orchestrator = AgenticBrainsOrchestrator()

    directive = orchestrator.run_agentic_loop(scalper, symbol="EURUSD")
    assert isinstance(directive, BrainOrchestratorDirective)
    assert directive.recommended_bias in ["BUY", "SELL", "HOLD"]
    assert directive.recommended_style in [
        "SCALPING",
        "DAY_TRADING",
        "SWING_TRADING",
        "POSITION_TRADING",
    ]
    assert 0.0 <= directive.confidence_score <= 100.0
    assert 0.0 <= directive.risk_ceiling_modifier <= 1.5
    assert len(directive.strategy_scores) >= 10
    assert len(directive.method_scores) >= 4

    d_dict = directive.to_dict()
    assert "recommended_bias" in d_dict
    assert "recommended_style" in d_dict
    assert "strategy_scores" in d_dict


def test_master_orchestrator_interventions():
    scalper = DummyScalper()
    scalper.daily_start_balance = 10000.0
    # Simulate equity drawdown
    scalper.conn.balance = 9700.0
    scalper.conn.equity = 9700.0  # 3% drawdown

    orchestrator = AgenticBrainsOrchestrator()
    directive = orchestrator.run_agentic_loop(scalper, symbol="EURUSD")

    # Master orchestrator should intervene and clamp risk modifier due to drawdown
    assert directive.risk_ceiling_modifier <= 0.50
    assert len(orchestrator.master_interventions) >= 1


def test_trading_engine_integration_decoupling():
    database.init_db()
    database._execute_with_retry("DELETE FROM trades WHERE status = 'OPEN'")

    scalper_brain = brain.ScalperBrain()

    # Generate dummy bars (needs >= 210 bars)
    history_bars = []
    base_price = 1.1000
    for i in range(220):
        history_bars.append(
            {
                "open": base_price + i * 0.0001,
                "high": base_price + i * 0.0001 + 0.0005,
                "low": base_price + i * 0.0001 - 0.0005,
                "close": base_price + i * 0.0001 + 0.0002,
            }
        )

    # Test evaluate with default directive
    res1 = scalper_brain.evaluate("EURUSD", history_bars, 10000.0)
    assert "decision" in res1
    assert "lot_size" in res1

    # Test evaluate with custom directive (50% risk modifier)
    directive = BrainOrchestratorDirective()
    directive.risk_ceiling_modifier = 0.5
    directive.guidance_notes.append("Testing custom risk modifier decoupling.")

    res2 = scalper_brain.evaluate(
        "EURUSD", history_bars, 10000.0, brain_directive=directive
    )
    assert res2["lot_size"] <= res1["lot_size"]
    assert "Testing custom risk modifier decoupling" in res2["explanation"]
