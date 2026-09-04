"""
Unit & Integration Tests for AI Stock Screener Engine (Animesh4002/ai-stock-screener Adaptation)
"""

from datetime import datetime
from institutional_integrations.ai_stock_screener_engine import AIStockScreenerEngine, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_ai_stock_screener_initialization() -> None:
    screener = AIStockScreenerEngine(min_composite_score=0.7)
    assert screener.min_composite_score == 0.7
    assert MAGIC_NUMBER == 9100026


def test_ai_stock_screener_evaluation() -> None:
    screener = AIStockScreenerEngine(min_composite_score=0.6)
    market_time = datetime(2025, 10, 15, 11, 0, 0)
    result = screener.screen_stock("TCS", pe_ratio=18.5, pb_ratio=3.2, roe_pct=22.5, momentum_score=0.8, current_price=3520.48, timestamp=market_time)

    assert result["symbol"] == "TCS"
    assert result["price"] == 3520.50  # 0.05 INR tick rounding
    assert result["passed"] is True
    assert result["magic_number"] == 9100026


def test_ai_stock_screener_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("animesh4002_ai_screener")
    assert plugin_cls is not None
    assert plugin_cls is AIStockScreenerEngine
