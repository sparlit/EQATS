# codespell:ignore MIS,IST
"""
Unit Test Suite for amitashwinibhagat/nse-swing-scanner Adaptation Module.
Verifies NSESwingScannerEngine Supertrend calculations, swing momentum scanning,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.nse_swing_scanner_engine import (
    MAGIC_NUMBER_NSE_SWING_SCANNER,
    NSESwingScannerAdapter,
    NSESwingScannerEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    generate_indian_market_history_bars,
)


def test_supertrend_calculation_and_swing_scan() -> None:
    engine = NSESwingScannerEngine(supertrend_period=10, supertrend_multiplier=3.0)
    bars = generate_indian_market_history_bars("NSE:INFY", count=40)

    # Set uptrend closes
    for i in range(20, 40):
        bars[i]["close"] = 1800.0 + i * 10.0
        bars[i]["high"] = bars[i]["close"] + 5.0
        bars[i]["low"] = bars[i]["close"] - 5.0

    st_res = engine.calculate_supertrend(
        [b["high"] for b in bars], [b["low"] for b in bars], [b["close"] for b in bars]
    )
    assert st_res["trend"] == "BULLISH"
    assert round(st_res["supertrend"] * 20) == st_res["supertrend"] * 20  # 0.05 INR tick

    scan_res = engine.scan_swing_setup(bars)
    assert scan_res["swing_signal"] == "BUY"
    assert scan_res["confidence"] >= 0.80
    assert scan_res["magic_number"] == MAGIC_NUMBER_NSE_SWING_SCANNER


def test_nse_swing_scanner_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("NSE_SWING_SCANNER")
    assert cls is NSESwingScannerAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="NSE_SWING_SCANNER", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="INFY", side="BUY", quantity=15, price=1820.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 1820.10
    assert res["ticket"].startswith("SWING_")
