"""
Unit & Integration Tests for Kite Option Chain Engine (anurag-roy/kite-option-chain Adaptation)
"""

from datetime import datetime
from institutional_integrations.kite_option_chain_engine import KiteOptionChainEngine, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_kite_option_chain_initialization() -> None:
    engine = KiteOptionChainEngine(pcr_bullish_threshold=1.2, pcr_bearish_threshold=0.7)
    assert engine.pcr_bullish_threshold == 1.2
    assert engine.pcr_bearish_threshold == 0.7
    assert MAGIC_NUMBER == 9100027


def test_kite_option_chain_analysis() -> None:
    engine = KiteOptionChainEngine()
    strikes = [25000.0, 25100.0, 25200.0, 25300.0, 25400.0]
    call_oi = [10000, 15000, 20000, 25000, 30000]
    put_oi = [35000, 30000, 25000, 20000, 15000]

    market_time = datetime(2025, 10, 15, 11, 15, 0)
    result = engine.analyze_option_chain("NIFTY", 25210.42, strikes, call_oi, put_oi, timestamp=market_time)

    assert result["symbol"] == "NIFTY"
    assert result["underlying_price"] == 25210.40  # 0.05 INR tick rounding
    assert result["pcr"] > 1.0
    assert result["sentiment"] in ["BULLISH", "NEUTRAL"]
    assert result["magic_number"] == 9100027


def test_kite_option_chain_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("anurag_roy_kite_optionchain")
    assert plugin_cls is not None
    assert plugin_cls is KiteOptionChainEngine
