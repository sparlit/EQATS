"""
Unit & Integration Tests for RaptorBT Engine (alphabench/raptorbt Adaptation)
"""

from datetime import datetime
from institutional_integrations.raptorbt_engine import RaptorBTEngine, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_raptorbt_engine_initialization() -> None:
    engine = RaptorBTEngine(initial_capital=500000.0, risk_free_rate=0.06)
    assert engine.initial_capital == 500000.0
    assert engine.risk_free_rate == 0.06
    assert MAGIC_NUMBER == 9100024


def test_raptorbt_engine_backtest_execution() -> None:
    engine = RaptorBTEngine(initial_capital=1000000.0)
    prices = [100.0, 102.0, 104.0, 103.0, 105.0, 108.0]
    signals = [1, 1, 1, -1, 1, 0]

    market_time = datetime(2025, 10, 15, 14, 0, 0)
    result = engine.run_backtest("NIFTY50", prices, signals, timestamp=market_time)

    assert result["symbol"] == "NIFTY50"
    assert result["status"] == "SUCCESS"
    assert result["total_returns_pct"] > 0
    assert result["sharpe_ratio"] != 0.0
    assert result["total_trades"] == 5
    assert result["magic_number"] == 9100024


def test_raptorbt_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("alphabench_raptorbt")
    assert plugin_cls is not None
    assert plugin_cls is RaptorBTEngine
