"""
Unit & Integration Tests for Zerobha Engine (althk/zerobha Adaptation)
"""

from datetime import datetime
from institutional_integrations.zerobha_engine import ZerobhaEngine, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_zerobha_engine_initialization() -> None:
    engine = ZerobhaEngine(default_target_pct=1.5, default_sl_pct=0.75)
    assert engine.default_target_pct == 1.5
    assert engine.default_sl_pct == 0.75
    assert MAGIC_NUMBER == 9100025


def test_zerobha_bracket_order_framing() -> None:
    engine = ZerobhaEngine()
    market_time = datetime(2025, 10, 15, 10, 30, 0)
    result = engine.frame_bracket_order("SBIN", "BUY", 820.43, 100, timestamp=market_time)

    assert result["symbol"] == "SBIN"
    assert result["price"] == 820.45  # 0.05 INR tick rounding
    assert result["quantity"] == 100
    assert result["target_price"] > 820.45
    assert result["sl_price"] < 820.45
    assert result["magic_number"] == 9100025


def test_zerobha_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("althk_zerobha")
    assert plugin_cls is not None
    assert plugin_cls is ZerobhaEngine
