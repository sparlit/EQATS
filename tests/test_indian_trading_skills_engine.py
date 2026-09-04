# codespell:ignore MIS,IST
"""
Unit Test Suite for ajeeshworkspace/indian-trading-skills Adaptation Module.
Verifies IndianTradingSkillsEngine VWAP bands calculation, EMA crossover setup,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.indian_trading_skills_engine import (
    MAGIC_NUMBER_INDIAN_TRADING_SKILLS,
    IndianTradingSkillsAdapter,
    IndianTradingSkillsEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    generate_indian_market_history_bars,
)


def test_vwap_bands_and_trading_setup() -> None:
    engine = IndianTradingSkillsEngine()
    bars = generate_indian_market_history_bars("NSE:RELIANCE", count=30)

    vwap_res = engine.calculate_vwap_bands(bars)
    assert vwap_res["vwap"] > 0
    assert vwap_res["upper_band_1"] > vwap_res["vwap"]
    assert vwap_res["lower_band_1"] < vwap_res["vwap"]
    assert round(vwap_res["vwap"] * 20) == vwap_res["vwap"] * 20  # 0.05 INR tick

    setup_res = engine.evaluate_trading_skills_setup(bars)
    assert "signal" in setup_res
    assert setup_res["magic_number"] == MAGIC_NUMBER_INDIAN_TRADING_SKILLS


def test_indian_trading_skills_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("INDIAN_TRADING_SKILLS")
    assert cls is IndianTradingSkillsAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="INDIAN_TRADING_SKILLS", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="RELIANCE", side="BUY", quantity=10, price=2850.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 2850.10
    assert res["ticket"].startswith("TRDSKILL_")
