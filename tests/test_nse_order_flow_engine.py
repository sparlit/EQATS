"""
Unit & Integration Tests for NSE Order Flow Engine (alloc7260/NSE Adaptation)
"""

from datetime import datetime
from institutional_integrations.nse_order_flow_engine import NSEOrderFlowEngine, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_nse_order_flow_engine_initialization() -> None:
    engine = NSEOrderFlowEngine(delta_threshold=2.0)
    assert engine.delta_threshold == 2.0
    assert MAGIC_NUMBER == 9100021


def test_nse_order_flow_evaluation() -> None:
    engine = NSEOrderFlowEngine()
    bid_vols = [5000.0, 4000.0, 3000.0, 2000.0, 1000.0]
    ask_vols = [1000.0, 800.0, 600.0, 400.0, 200.0]

    market_time = datetime(2025, 10, 15, 11, 30, 0)
    result = engine.evaluate_order_flow("NIFTY25OCTFUT", bid_vols, ask_vols, 25210.37, timestamp=market_time)

    assert result["symbol"] == "NIFTY25OCTFUT"
    assert result["price"] == 25210.35  # 0.05 INR tick size rounding
    assert result["action"] == "BUY"
    assert result["ofi"] > 0.35
    assert result["cvd"] == 12000.0
    assert result["magic_number"] == 9100021


def test_nse_order_flow_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("alloc7260_nse_orderflow")
    assert plugin_cls is not None
    assert plugin_cls is NSEOrderFlowEngine
