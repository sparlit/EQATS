# codespell:ignore MIS,IST
"""
Unit Test Suite for aadityatamrakar/option_chain_analysis Adaptation Module.
Verifies OptionChainAnalyzerEngine PCR, Max Pain, Black-Scholes Greeks,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.option_chain_analysis_engine import (
    MAGIC_NUMBER_OPTION_CHAIN,
    OptionChainAdapter,
    OptionChainAnalyzerEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
)


def test_black_scholes_greeks_math() -> None:
    engine = OptionChainAnalyzerEngine(risk_free_rate=0.07)
    greeks_call = engine.calculate_bs_greeks(
        spot=24500.0, strike=24500.0, time_to_expiry_years=0.08, iv=0.18, option_type="CALL"
    )
    assert greeks_call["price"] > 0
    assert round(greeks_call["price"] * 20) == greeks_call["price"] * 20  # 0.05 INR tick
    assert 0.40 <= greeks_call["delta"] <= 0.60
    assert greeks_call["gamma"] > 0

    greeks_put = engine.calculate_bs_greeks(
        spot=24500.0, strike=24500.0, time_to_expiry_years=0.08, iv=0.18, option_type="PUT"
    )
    assert greeks_put["price"] > 0
    assert -0.60 <= greeks_put["delta"] <= -0.40


def test_pcr_and_max_pain_calculation() -> None:
    engine = OptionChainAnalyzerEngine()
    mock_chain = [
        {"strike": 24000.0, "call_oi": 10000, "put_oi": 80000},
        {"strike": 24200.0, "call_oi": 20000, "put_oi": 60000},
        {"strike": 24400.0, "call_oi": 30000, "put_oi": 40000},
        {"strike": 24600.0, "call_oi": 50000, "put_oi": 20000},
        {"strike": 24800.0, "call_oi": 70000, "put_oi": 10000},
    ]

    analysis = engine.analyze_option_chain("NIFTY", spot_price=24500.0, option_chain=mock_chain)

    # Put OI = 210000, Call OI = 180000 -> PCR = 210000 / 180000 = 1.1667
    assert analysis["total_put_oi"] == 210000
    assert analysis["total_call_oi"] == 180000
    assert analysis["pcr"] > 1.0
    assert analysis["max_pain_strike"] > 0
    assert analysis["magic_number"] == MAGIC_NUMBER_OPTION_CHAIN


def test_option_chain_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("OPTION_CHAIN_ANALYSIS")
    assert cls is OptionChainAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="OPTION_CHAIN_ANALYSIS", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="NIFTY24MAR24500CE", side="BUY", quantity=50, price=180.12, product="NRML")
    assert res["success"] is True
    assert res["price"] == 180.10
    assert res["ticket"].startswith("OPTCHAIN_")
