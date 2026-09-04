# codespell:ignore MIS,IST
"""
Unit Test Suite for akashnag/scripwatch Adaptation Module.
Verifies ScripWatchEngine 52-week proximity triggers, watchlist alert evaluations,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.scripwatch_engine import (
    MAGIC_NUMBER_SCRIPWATCH,
    ScripWatchAdapter,
    ScripWatchEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
)


def test_scripwatch_triggers_eval() -> None:
    engine = ScripWatchEngine(proximity_pct=2.0)

    # Test near 52-week high trigger
    res_high = engine.evaluate_stock_triggers(
        symbol="HDFCBANK", current_price=1680.12, fifty_two_week_high=1700.0, fifty_two_week_low=1350.0
    )
    assert res_high["signal"] == "BUY"
    assert res_high["near_52w_high"] is True
    assert len(res_high["triggers_active"]) == 1
    assert res_high["magic_number"] == MAGIC_NUMBER_SCRIPWATCH

    # Test near 52-week low trigger
    res_low = engine.evaluate_stock_triggers(
        symbol="HDFCBANK", current_price=1360.0, fifty_two_week_high=1700.0, fifty_two_week_low=1350.0
    )
    assert res_low["signal"] == "SELL"
    assert res_low["near_52w_low"] is True


def test_scripwatch_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("SCRIPWATCH")
    assert cls is ScripWatchAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="SCRIPWATCH", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="HDFCBANK", side="BUY", quantity=10, price=1650.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 1650.10
    assert res["ticket"].startswith("SCRIP_")
