"""
Unit & Integration Tests for BuyNSell Engine (akt114/BuyNSell Adaptation)
"""

from datetime import datetime
from institutional_integrations.buy_n_sell_engine import BuyNSellEngine, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_buy_n_sell_engine_initialization() -> None:
    engine = BuyNSellEngine(fast_period=5, slow_period=10)
    assert engine.fast_period == 5
    assert engine.slow_period == 10
    assert MAGIC_NUMBER == 9100020


def test_buy_n_sell_signal_evaluation() -> None:
    engine = BuyNSellEngine(fast_period=3, slow_period=5)
    prices = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
    volumes = [1000.0, 1200.0, 1100.0, 1500.0, 2000.0, 2500.0]

    # Test market open time (10:00 AM IST)
    market_time = datetime(2025, 10, 15, 10, 0, 0)
    result = engine.evaluate_signal("RELIANCE", prices, volumes, 110.03, timestamp=market_time)

    assert result["symbol"] == "RELIANCE"
    assert result["price"] == 110.05  # 0.05 INR tick rounding
    assert result["action"] == "BUY"
    assert result["volume_surge"] is True
    assert result["magic_number"] == 9100020


def test_buy_n_sell_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("akt114_buynsell")
    assert plugin_cls is not None
    assert plugin_cls is BuyNSellEngine
