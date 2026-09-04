"""
Unit & Integration Tests for OsEngine Trader (AlexWan/OsEngine Adaptation)
"""

from datetime import datetime
from institutional_integrations.osengine_trader import OsEngineTrader, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_osengine_trader_initialization() -> None:
    trader = OsEngineTrader(channel_period=10, max_drawdown_pct=1.5)
    assert trader.channel_period == 10
    assert trader.max_drawdown_pct == 1.5
    assert MAGIC_NUMBER == 9100022


def test_osengine_trader_breakout_evaluation() -> None:
    trader = OsEngineTrader(channel_period=5, max_drawdown_pct=2.0)
    highs = [100.0, 102.0, 104.0, 106.0, 108.0]
    lows = [98.0, 100.0, 102.0, 104.0, 106.0]
    closes = [99.0, 101.0, 103.0, 105.0, 107.0]

    market_time = datetime(2025, 10, 15, 12, 0, 0)
    result = trader.evaluate_breakout("TATASTEEL", highs, lows, closes, 108.53, timestamp=market_time)

    assert result["symbol"] == "TATASTEEL"
    assert result["price"] == 108.55  # 0.05 INR tick rounding
    assert result["action"] == "BUY"
    assert result["upper_channel"] == 108.0
    assert result["magic_number"] == 9100022


def test_osengine_trader_drawdown_exit() -> None:
    trader = OsEngineTrader(channel_period=5, max_drawdown_pct=2.0)
    highs = [100.0, 102.0, 104.0, 106.0, 108.0]
    lows = [98.0, 100.0, 102.0, 104.0, 106.0]
    closes = [99.0, 101.0, 103.0, 105.0, 107.0]

    market_time = datetime(2025, 10, 15, 12, 0, 0)
    # Entry at 100.0, current price drops to 97.0 (3.0% drawdown >= 2.0%)
    result = trader.evaluate_breakout(
        "TATASTEEL", highs, lows, closes, 97.0, entry_price=100.0, timestamp=market_time
    )

    assert result["action"] == "SELL"
    assert result["confidence"] == 1.0
    assert "Trailing drawdown boundary breach" in result["reason"]


def test_osengine_trader_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("alexwan_osengine")
    assert plugin_cls is not None
    assert plugin_cls is OsEngineTrader
