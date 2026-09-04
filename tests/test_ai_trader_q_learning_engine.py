# codespell:ignore MIS,IST
"""
Unit Test Suite for aaryansinha16/AI-trader Adaptation Module.
Verifies AITraderQLearningEngine state encoding, Bellman Q-value updates,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.ai_trader_q_learning_engine import (
    MAGIC_NUMBER_AI_TRADER_Q,
    AITraderQLearningAdapter,
    AITraderQLearningEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    generate_indian_market_history_bars,
)


def test_q_learning_state_encoding_and_bellman_update() -> None:
    engine = AITraderQLearningEngine(alpha=0.1, gamma=0.95, epsilon=0.0)
    bars = generate_indian_market_history_bars("NSE:INFY", count=20)
    closes = [b["close"] for b in bars]

    state = engine.encode_state(closes, rsi_val=65.0)
    assert isinstance(state, tuple)
    assert len(state) == 3

    # Test Q-value update
    initial_q = engine.update_q_value(state=state, action=1, reward=10.0, next_state=(1, 1, 1))
    assert initial_q > 0.0

    eval_res = engine.evaluate_trading_decision(bars, rsi_val=65.0)
    assert "decision" in eval_res
    assert eval_res["magic_number"] == MAGIC_NUMBER_AI_TRADER_Q


def test_ai_trader_q_learning_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("AI_TRADER_Q_LEARNING")
    assert cls is AITraderQLearningAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="AI_TRADER_Q_LEARNING", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="INFY", side="BUY", quantity=10, price=1820.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 1820.10
    assert res["ticket"].startswith("AIQ_")
