"""
Unit & Integration Tests for AI AlgoTrading Agent (algotrading-lab/ai-algotrading-agent Adaptation)
"""

from datetime import datetime
from institutional_integrations.ai_algotrading_agent import AIAlgoTradingAgent, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_ai_algotrading_agent_initialization() -> None:
    agent = AIAlgoTradingAgent(rsi_period=14, macd_fast=12, macd_slow=26)
    assert agent.rsi_period == 14
    assert agent.macd_fast == 12
    assert agent.macd_slow == 26
    assert MAGIC_NUMBER == 9100023


def test_ai_algotrading_agent_decision_evaluation() -> None:
    agent = AIAlgoTradingAgent(rsi_period=5, macd_fast=3, macd_slow=6)
    # Price drop followed by uptick to generate oversold RSI + bullish MACD
    closes = [100.0, 95.0, 90.0, 85.0, 80.0, 82.0, 84.0]

    market_time = datetime(2025, 10, 15, 13, 0, 0)
    result = agent.evaluate_agent_decision("INFY", closes, 84.03, timestamp=market_time)

    assert result["symbol"] == "INFY"
    assert result["price"] == 84.05  # 0.05 INR tick rounding
    assert result["action"] in ["BUY", "HOLD"]
    assert result["magic_number"] == 9100023


def test_ai_algotrading_agent_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("algotrading_lab_agent")
    assert plugin_cls is not None
    assert plugin_cls is AIAlgoTradingAgent
