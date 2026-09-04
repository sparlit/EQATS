# codespell:ignore MIS,IST
"""
Unit Test Suite for akashyadavv/AlgoTradingNSE Adaptation Module.
Verifies AlgoTradingNSEEngine volume breakout scanning, Bracket Order logic,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.algo_trading_nse_engine import (
    MAGIC_NUMBER_ALGO_TRADING_NSE,
    AlgoTradingNSEAdapter,
    AlgoTradingNSEEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    generate_indian_market_history_bars,
)


def test_algo_trading_nse_breakout_scanner() -> None:
    engine = AlgoTradingNSEEngine(target_rr_ratio=2.0)
    bars = generate_indian_market_history_bars("NSE:ICICIBANK", count=25)

    # Set last bar with volume surge and price breakout
    donchian_high = max(b["high"] for b in bars[-20:-1])
    bars[-1]["close"] = donchian_high + 10.0
    bars[-1]["volume"] = 50000.0  # High volume surge

    scan_res = engine.scan_momentum_breakout(bars, volume_surge_factor=1.2)
    assert scan_res["breakout"] is True
    assert scan_res["signal"] == "BUY"
    assert scan_res["tp"] > scan_res["entry_price"]
    assert scan_res["magic_number"] == MAGIC_NUMBER_ALGO_TRADING_NSE


def test_algo_trading_nse_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("ALGO_TRADING_NSE")
    assert cls is AlgoTradingNSEAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="ALGO_TRADING_NSE", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="ICICIBANK", side="BUY", quantity=25, price=1220.12, product="MIS")
    assert res["success"] is True
    assert res["price"] == 1220.10
    assert res["ticket"].startswith("ALGONSE_")
