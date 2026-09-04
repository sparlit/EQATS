# codespell:ignore MIS,IST
"""
Unit Test Suite for akshayz14/indian-stock-tracker Adaptation Module.
Verifies IndianStockTrackerEngine gainers/losers classification, portfolio allocation,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.indian_stock_tracker_engine import (
    MAGIC_NUMBER_INDIAN_STOCK_TRACKER,
    IndianStockTrackerAdapter,
    IndianStockTrackerEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
)


def test_gainers_losers_and_portfolio_allocation() -> None:
    engine = IndianStockTrackerEngine()
    mock_quotes = [
        {"symbol": "RELIANCE", "last_price": 2850.12, "prev_close": 2800.0},
        {"symbol": "INFY", "last_price": 1820.0, "prev_close": 1800.0},
        {"symbol": "TCS", "last_price": 4100.0, "prev_close": 4200.0},
        {"symbol": "SBIN", "last_price": 820.0, "prev_close": 840.0},
    ]

    gl_res = engine.track_symbols_gainers_losers(mock_quotes)
    assert len(gl_res["top_gainers"]) == 2
    assert len(gl_res["top_losers"]) == 2
    assert gl_res["top_gainers"][0]["symbol"] == "RELIANCE"
    assert gl_res["top_losers"][0]["symbol"] == "SBIN"
    assert gl_res["magic_number"] == MAGIC_NUMBER_INDIAN_STOCK_TRACKER

    mock_positions = [
        {"quantity": 10, "price": 2850.0, "product": "CNC"},
        {"quantity": 50, "price": 820.0, "product": "MIS"},
        {"quantity": 20, "price": 1820.0, "product": "NRML"},
    ]

    alloc = engine.evaluate_portfolio_allocation(mock_positions)
    assert alloc["total_value"] > 0
    assert alloc["equity_exposure_pct"] > 0
    assert alloc["intraday_exposure_pct"] > 0
    assert alloc["fo_exposure_pct"] > 0


def test_indian_stock_tracker_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("INDIAN_STOCK_TRACKER")
    assert cls is IndianStockTrackerAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="INDIAN_STOCK_TRACKER", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="RELIANCE", side="BUY", quantity=10, price=2850.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 2850.10
    assert res["ticket"].startswith("STRK_")
