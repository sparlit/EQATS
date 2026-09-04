# codespell:ignore MIS,IST
"""
Unit Test Suite for aniruddhsujish/NSETradeAgents Adaptation Module.
Verifies NSETradeAgentsSuite multi-agent deliberations, consensus voting,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.nse_trade_agents_suite import (
    MAGIC_NUMBER_NSE_TRADE_AGENTS,
    NSETradeAgentsAdapter,
    NSETradeAgentsSuite,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    generate_indian_market_history_bars,
)


def test_nse_trade_agents_deliberation() -> None:
    suite = NSETradeAgentsSuite()
    bars = generate_indian_market_history_bars("NSE:RELIANCE", count=30)

    # Modify closes to trigger bullish technical & structure votes
    for i in range(15, 30):
        bars[i]["close"] = 2850.0 + i * 5.0
        bars[i]["high"] = bars[i]["close"] + 2.0
        bars[i]["low"] = bars[i]["close"] - 2.0

    consensus = suite.deliberate_consensus("RELIANCE", bars, pcr_val=1.35)
    assert consensus["consensus_decision"] == "BUY"
    assert consensus["confidence"] >= 0.66
    assert consensus["magic_number"] == MAGIC_NUMBER_NSE_TRADE_AGENTS
    assert "technical" in consensus["agent_deliberations"]


def test_nse_trade_agents_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("NSE_TRADE_AGENTS")
    assert cls is NSETradeAgentsAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="NSE_TRADE_AGENTS", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="RELIANCE", side="BUY", quantity=10, price=2850.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 2850.10
    assert res["ticket"].startswith("NSEAG_")
